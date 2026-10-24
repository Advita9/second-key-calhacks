"""ClaudeMargaret: the persona played by Claude via structured outputs.

Any failure (exception, refusal, max_tokens, empty parse, validation, a long digit run in the
reply) returns `MargaretTurn(SAFE_REPLY, persuasion unchanged, None)`. Model output is data,
never an instruction; the guards below are deterministic and run after parsing.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from kernel.llm.cache import ResponseCache
from kernel.margaret.types import (
    DRAFT_THRESHOLD,
    MAX_STEP,
    SAFE_REPLY,
    DraftPayment,
    EvidenceLike,
    MargaretTurn,
    clamp01,
)
from kernel.models import Rail

log = logging.getLogger("second_key.margaret")

_LONG_DIGITS = re.compile(r"\d{8,}")
MAX_HISTORY_ITEMS = 40
MAX_PLAYER_CHARS = 2000
# Structured output on current Sonnet models spends several hundred output tokens before the
# JSON text appears; 400 truncated 2 of 8 demo turns (stop_reason max_tokens, 38 chars of JSON).
# Not part of the cache key, so raising it keeps existing entries valid.
MAX_TOKENS = 1600


RailName = Literal["WIRE", "ACH", "ZELLE", "CARD"]


class DraftOut(BaseModel):
    """Rail is a string literal (not the Rail enum) so strict validation behaves the same for
    JSON from the API and for dicts replayed from the cache."""

    model_config = ConfigDict(strict=True, extra="forbid")
    amount_cents: int
    payee_name: str
    rail: RailName


class MargaretOut(BaseModel):
    """Structured output schema for the model. Plain types only; constraints are enforced
    after parsing so a schema rejection cannot leak into a state change."""

    model_config = ConfigDict(strict=True, extra="forbid")
    reply: str
    persuasion: float
    draft: DraftOut | None


def make_client(api_key: str, timeout: float = 7.0) -> anthropic.Anthropic:
    """No retries; the room turn has a hard budget. `build_margaret` passes 12 s because the
    persona call is not inside the kernel's 8 s extractor budget."""
    return anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)


def _speaker_line(item: EvidenceLike) -> str:
    return f"[{item.id}] {item.speaker}: {item.text}"


def build_messages(
    history: Sequence[EvidenceLike], player_text: str, persuasion: float
) -> list[dict[str, Any]]:
    """History as alternating transcript turns, then the player's text. Margaret's own lines
    become assistant turns; everyone else is a user turn tagged with the evidence id."""
    msgs: list[dict[str, Any]] = []
    for item in list(history)[-MAX_HISTORY_ITEMS:]:
        if item.speaker.strip().lower() == "margaret":
            if not msgs:
                msgs.append({"role": "user", "content": "(call begins)"})
            msgs.append({"role": "assistant", "content": item.text})
        else:
            msgs.append({"role": "user", "content": _speaker_line(item)})
    msgs.append(
        {
            "role": "user",
            "content": (
                f"caller: {player_text[:MAX_PLAYER_CHARS]}\n\n"
                f"(current persuasion: {persuasion:.2f}. Reply as Margaret.)"
            ),
        }
    )
    return msgs


def _sanitize_reply(text: str) -> str | None:
    cleaned = text.replace("—", ",").replace("–", ",").strip()
    if not cleaned or _LONG_DIGITS.search(cleaned):
        return None
    return cleaned


def turn_from_parsed(parsed: MargaretOut, current: float) -> MargaretTurn | None:
    """Deterministic guards over model output. None means fail closed."""
    reply = _sanitize_reply(parsed.reply)
    if reply is None:
        return None
    lo, hi = clamp01(current - MAX_STEP), clamp01(current + MAX_STEP)
    persuasion = round(min(hi, max(lo, clamp01(parsed.persuasion))), 4)
    draft: DraftPayment | None = None
    if parsed.draft is not None and persuasion > DRAFT_THRESHOLD:
        try:
            draft = DraftPayment(
                amount_cents=parsed.draft.amount_cents,
                payee_name=parsed.draft.payee_name.strip()[:80] or "the caller",
                rail=Rail(parsed.draft.rail),
            )
        except ValidationError:
            draft = None
    return MargaretTurn(reply=reply, persuasion=persuasion, draft_payment=draft)


class ClaudeMargaret:
    name = "claude"
    is_mock = False

    def __init__(
        self,
        client: anthropic.Anthropic,
        *,
        model: str,
        cache: ResponseCache,
        persona_system: str,
        max_tokens: int = MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._cache = cache
        self._system = persona_system
        self._max_tokens = max_tokens
        self._schema = MargaretOut.model_json_schema()

    def reply(
        self, history: Sequence[EvidenceLike], player_text: str, persuasion: float
    ) -> MargaretTurn:
        safe = MargaretTurn(reply=SAFE_REPLY, persuasion=persuasion, draft_payment=None)
        try:
            return self._reply(history, player_text, persuasion) or safe
        except ValidationError as exc:
            # Field names and error types only; never the model's values or the prompt.
            where = [(e["type"], ".".join(str(x) for x in e["loc"])) for e in exc.errors()]
            log.warning("margaret.turn mode=claude failed error=ValidationError where=%s", where)
            return safe
        except Exception as exc:  # fail closed on anything
            log.warning("margaret.turn mode=claude failed error=%s", type(exc).__name__)
            return safe

    def _reply(
        self, history: Sequence[EvidenceLike], player_text: str, persuasion: float
    ) -> MargaretTurn | None:
        messages = build_messages(history, player_text, persuasion)
        key = ResponseCache.key(self._model, self._system, messages, self._schema)
        cached = self._cache.get(key)
        source = "cache"
        started = time.perf_counter()
        if cached is None:
            if self._cache.replay_only:
                log.warning("margaret.turn mode=claude cache_miss replay_only=1")
                return None
            source = "api"
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system,
                messages=messages,  # type: ignore[arg-type]
                output_format=MargaretOut,
            )
            stop_reason = str(response.stop_reason)
            if stop_reason in {"refusal", "max_tokens"}:
                log.warning("margaret.turn mode=claude stop_reason=%s", stop_reason)
                return None
            parsed_obj = response.parsed_output
            if parsed_obj is None:
                return None
            cached = {"parsed": parsed_obj.model_dump(mode="json"), "stop_reason": stop_reason}
            self._cache.put(key, cached)
        parsed = MargaretOut.model_validate(cached.get("parsed"))
        turn = turn_from_parsed(parsed, persuasion)
        log.info(
            "margaret.turn mode=claude source=%s latency_ms=%d persuasion=%.2f draft=%s ok=%s",
            source,
            int((time.perf_counter() - started) * 1000),
            turn.persuasion if turn else persuasion,
            bool(turn and turn.draft_payment),
            turn is not None,
        )
        return turn
