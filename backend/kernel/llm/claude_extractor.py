"""ClaudeExtractor: structured-output call to the Messages API, cached, fail closed.

Flow: build per-request output model (Literal of evidence ids) -> cache lookup -> on miss call
`client.messages.parse(...)` -> reject refusal/truncation/missing output -> re-validate the
parsed JSON against the per-request model (cached entries too; they are untrusted files) ->
`sanitize` drops spans that are not verbatim substrings -> ExtractorResult.

Every failure raises ExtractorError. The kernel maps that to HOLD with rule X-00. This module
never imports state, service, certs, attest or db (boundary test).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

import anthropic
from pydantic import ValidationError

from kernel.llm.cache import ResponseCache
from kernel.llm.prompts import EXTRACTOR_SYSTEM, build_user_message
from kernel.llm.schema import build_output_model, sanitize
from kernel.llm.types import EvidenceItem, ExtractorError, ExtractorResult
from kernel.models import PaymentIn

log = logging.getLogger("second_key.llm.claude")

CLIENT_TIMEOUT_S = 7.0
BAD_STOP_REASONS = ("refusal", "max_tokens")


def make_client(api_key: str) -> anthropic.Anthropic:
    """One attempt, 7s budget: the kernel's own extractor timeout is 8s."""
    return anthropic.Anthropic(api_key=api_key, timeout=CLIENT_TIMEOUT_S, max_retries=0)


class ClaudeExtractor:
    def __init__(
        self,
        client: anthropic.Anthropic,
        *,
        model: str,
        cache: ResponseCache,
        max_tokens: int = 1024,
        max_signals: int = 12,
        effort: str | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.cache = cache
        self.max_tokens = max_tokens
        self.max_signals = max_signals
        self.effort = effort

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        try:
            return self._extract(tuple(conversation), payment)
        except ExtractorError:
            raise
        except Exception as e:  # noqa: BLE001  anything else at the model boundary is X-00
            log.warning("extractor.error", extra={"error": type(e).__name__})
            raise ExtractorError(f"{type(e).__name__}: {e}") from e

    def _extract(
        self, conversation: tuple[EvidenceItem, ...], payment: PaymentIn
    ) -> ExtractorResult:
        if not conversation:
            return ExtractorResult()
        output_model = build_output_model([e.id for e in conversation])
        schema = output_model.model_json_schema()
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_user_message(conversation, payment)}
        ]
        key = ResponseCache.key(self.model, EXTRACTOR_SYSTEM, messages, schema)

        started = time.perf_counter()
        cached = self.cache.get(key)
        if cached is not None:
            parsed_raw, stop_reason, hit = cached.get("parsed"), cached.get("stop_reason"), True
        elif self.cache.replay_only:
            raise ExtractorError("replay-only cache miss (DEMO_MODE)")
        else:
            parsed_raw, stop_reason, hit = self._call(output_model, messages)
            self.cache.put(key, {"parsed": parsed_raw, "stop_reason": stop_reason})
        latency_ms = int((time.perf_counter() - started) * 1000)

        if stop_reason in BAD_STOP_REASONS:
            raise ExtractorError(f"stop_reason={stop_reason}")
        if not isinstance(parsed_raw, dict):
            raise ExtractorError("parsed output is not an object")
        try:
            validated = output_model.model_validate(parsed_raw)
        except ValidationError as e:
            raise ExtractorError(f"output failed schema: {e.error_count()} error(s)") from None
        result = sanitize(
            validated.model_dump(mode="json"), conversation, max_signals=self.max_signals
        )
        dropped = len(validated.model_dump()["signals"]) - len(result.signals)
        log.info(
            "extractor.claude",
            extra={
                "model": self.model,
                "cache_hit": hit,
                "latency_ms": latency_ms,
                "stop_reason": stop_reason,
                "n_items": len(conversation),
                "n_signals": len(result.signals),
                "n_dropped": max(dropped, 0),
            },
        )
        return result

    def _call(
        self, output_model: type[Any], messages: list[dict[str, Any]]
    ) -> tuple[Any, str | None, bool]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": EXTRACTOR_SYSTEM,
            "messages": messages,
            "output_format": output_model,
        }
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        response = self.client.messages.parse(**kwargs)
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason in BAD_STOP_REASONS:
            raise ExtractorError(f"stop_reason={stop_reason}")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ExtractorError("parsed_output is None")
        dump = parsed.model_dump(mode="json")
        if not isinstance(dump, dict):
            raise ExtractorError("parsed_output did not dump to an object")
        # Re-validate against THIS request's model before caching: the client may be a fake,
        # and the per-request Literal is what makes foreign ids impossible.
        try:
            output_model.model_validate(dump)
        except ValidationError as e:
            raise ExtractorError(f"output failed schema: {e.error_count()} error(s)") from None
        return dump, stop_reason if isinstance(stop_reason, str) else None, False
