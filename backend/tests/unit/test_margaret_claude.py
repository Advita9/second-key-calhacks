"""ClaudeMargaret against a fake client replaying tests/fixtures/llm/margaret_turn.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import pytest

from kernel.llm.types import EvidenceItem
from kernel.margaret._cache import ResponseCache
from kernel.margaret.claude import (
    ClaudeMargaret,
    MargaretOut,
    build_messages,
    make_client,
    turn_from_parsed,
)
from kernel.margaret.factory import build_margaret
from kernel.margaret.mock import MockMargaret
from kernel.margaret.types import SAFE_REPLY, DraftPayment, MargaretTurn
from kernel.models import Rail

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "margaret_turn.json"
RECORDED = json.loads(FIXTURE.read_text())
SYSTEM = "You are Margaret. Test persona."
LONG_DIGITS = re.compile(r"\d{8,}")


class FakeMessages:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    def __init__(self, *responses: Any) -> None:
        self.messages = FakeMessages(list(responses))


def recorded(i: int) -> SimpleNamespace:
    r = RECORDED["turns"][i]["response"]
    return SimpleNamespace(
        stop_reason=r["stop_reason"], parsed_output=MargaretOut.model_validate(r["parsed"])
    )


def ok(parsed: dict[str, Any] | None, stop_reason: str = "end_turn") -> SimpleNamespace:
    out = None if parsed is None else MargaretOut.model_validate(parsed)
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=out)


def make(
    tmp_path: Path, *responses: Any, replay_only: bool = False
) -> tuple[ClaudeMargaret, FakeClient]:
    client = FakeClient(*responses)
    m = ClaudeMargaret(
        cast(anthropic.Anthropic, client),
        model=RECORDED["model"],
        cache=ResponseCache(tmp_path / "llm", replay_only=replay_only),
        persona_system=SYSTEM,
    )
    return m, client


def ev(i: int, speaker: str, text: str) -> EvidenceItem:
    return EvidenceItem(id=f"EV-{i:04d}", speaker=speaker, text=text)


def test_recorded_two_turn_conversation(tmp_path: Path) -> None:
    m, client = make(tmp_path, recorded(0), recorded(1))
    t0 = RECORDED["turns"][0]
    turn0 = m.reply([], t0["player_text"], t0["persuasion_in"])
    assert turn0.reply and turn0.reply != SAFE_REPLY
    assert 0.0 <= turn0.persuasion <= 1.0
    assert turn0.draft_payment is None

    t1 = RECORDED["turns"][1]
    history = [ev(1, "caller", t0["player_text"]), ev(2, "margaret", turn0.reply)]
    turn1 = m.reply(history, t1["player_text"], turn0.persuasion)
    assert turn1.reply != SAFE_REPLY
    assert turn1.persuasion >= turn0.persuasion
    if turn1.persuasion > 0.75:
        assert turn1.draft_payment is not None
        assert turn1.draft_payment.amount_cents == 185000
        assert turn1.draft_payment.rail is Rail.WIRE
    for t in (turn0, turn1):
        assert "—" not in t.reply and not LONG_DIGITS.search(t.reply)
    assert len(client.messages.calls) == 2


def test_parse_kwargs_shape(tmp_path: Path) -> None:
    m, client = make(tmp_path, recorded(0))
    history = [ev(1, "margaret", "Hello?"), ev(2, "caller", "Hi Margaret")]
    m.reply(history, "This is the IRS", 0.2)
    kw = client.messages.calls[0]
    assert "temperature" not in kw and "thinking" not in kw
    assert kw["model"] == RECORDED["model"]
    assert kw["system"] == SYSTEM
    assert kw["output_format"] is MargaretOut
    assert isinstance(kw["max_tokens"], int)
    msgs = kw["messages"]
    assert msgs[0]["role"] == "user"  # transcript always opens with a user turn
    assert [x["role"] for x in msgs] == ["user", "assistant", "user", "user"]
    assert "This is the IRS" in msgs[-1]["content"]
    assert "[EV-0002] caller: Hi Margaret" in msgs[2]["content"]


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("boom"),
        anthropic.APITimeoutError(request=cast(Any, SimpleNamespace())),
        ok(None),
        ok({"reply": "x", "persuasion": 0.9, "draft": None}, stop_reason="refusal"),
        ok({"reply": "x", "persuasion": 0.9, "draft": None}, stop_reason="max_tokens"),
        SimpleNamespace(stop_reason="end_turn", parsed_output=SimpleNamespace(bad=1)),
        ok({"reply": "the number is 12345678", "persuasion": 0.3, "draft": None}),
        ok({"reply": "   ", "persuasion": 0.3, "draft": None}),
    ],
)
def test_every_failure_is_safe_reply_with_unchanged_persuasion(
    tmp_path: Path, response: Any
) -> None:
    m, _ = make(tmp_path, response)
    turn = m.reply([], "This is the IRS", 0.37)
    assert turn == MargaretTurn(reply=SAFE_REPLY, persuasion=0.37, draft_payment=None)


def test_validation_error_from_model_is_safe(tmp_path: Path) -> None:
    class Weird:
        stop_reason = "end_turn"

        @property
        def parsed_output(self) -> Any:
            raise ValueError("could not parse")

    m, _ = make(tmp_path, Weird())
    assert m.reply([], "hi", 0.5) == MargaretTurn(reply=SAFE_REPLY, persuasion=0.5)


def test_strict_output_model_rejects_extra_and_wrong_types() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MargaretOut.model_validate({"reply": "x", "persuasion": "0.5", "draft": None})
    with pytest.raises(ValidationError):
        MargaretOut.model_validate({"reply": "x", "persuasion": 0.5, "draft": None, "release": 1})
    with pytest.raises(ValidationError):
        MargaretOut.model_validate(
            {
                "reply": "x",
                "persuasion": 0.9,
                "draft": {"amount_cents": 1, "payee_name": "a", "rail": "CASH"},
            }
        )


def test_guards_after_parse() -> None:
    # persuasion step clamp (never more than MAX_STEP per turn)
    t = turn_from_parsed(MargaretOut(reply="ok", persuasion=1.0, draft=None), 0.2)
    assert t is not None and t.persuasion == 0.45
    t = turn_from_parsed(MargaretOut(reply="ok", persuasion=0.0, draft=None), 0.9)
    assert t is not None and t.persuasion == 0.65
    # draft dropped when persuasion ends at or below the threshold
    d = {"amount_cents": 1000, "payee_name": "Agent Daniels", "rail": "WIRE"}
    t = turn_from_parsed(
        MargaretOut.model_validate({"reply": "ok", "persuasion": 0.9, "draft": d}), 0.3
    )
    assert t is not None and t.persuasion == 0.55 and t.draft_payment is None
    t = turn_from_parsed(
        MargaretOut.model_validate({"reply": "ok", "persuasion": 0.9, "draft": d}), 0.7
    )
    assert t is not None and t.draft_payment == DraftPayment(
        amount_cents=1000, payee_name="Agent Daniels", rail=Rail.WIRE
    )
    # non-positive amount in the draft -> no draft, reply kept
    bad = {"amount_cents": 0, "payee_name": "x", "rail": "ACH"}
    t = turn_from_parsed(
        MargaretOut.model_validate({"reply": "ok", "persuasion": 0.9, "draft": bad}), 0.8
    )
    assert t is not None and t.draft_payment is None and t.reply == "ok"
    # em dashes are replaced
    t = turn_from_parsed(MargaretOut(reply="Oh — dear", persuasion=0.5, draft=None), 0.5)
    assert t is not None and "—" not in t.reply


def test_cache_hit_skips_client(tmp_path: Path) -> None:
    m, client = make(tmp_path, recorded(0), RuntimeError("must not be called"))
    a = m.reply([], "This is the IRS", 0.2)
    b = m.reply([], "This is the IRS", 0.2)
    assert a == b and a.reply != SAFE_REPLY
    assert len(client.messages.calls) == 1
    assert ResponseCache(tmp_path / "llm").root.exists()


def test_replay_only_miss_is_safe(tmp_path: Path) -> None:
    m, client = make(tmp_path, recorded(0), replay_only=True)
    assert m.reply([], "This is the IRS", 0.2) == MargaretTurn(reply=SAFE_REPLY, persuasion=0.2)
    assert client.messages.calls == []


def test_cache_key_changes_with_any_input() -> None:
    msgs = build_messages([], "hi", 0.2)
    base = ResponseCache.key("m", "s", msgs, {"a": 1})
    assert ResponseCache.key("m", "s", build_messages([], "hi", 0.3), {"a": 1}) != base
    assert ResponseCache.key("m2", "s", msgs, {"a": 1}) != base
    assert ResponseCache.key("m", "s2", msgs, {"a": 1}) != base
    assert ResponseCache.key("m", "s", msgs, {"a": 2}) != base
    assert ResponseCache.key("m", "s", list(msgs), {"a": 1}) == base


def test_make_client_timeout_and_no_retries() -> None:
    c = make_client("sk-test")
    assert c.max_retries == 0
    assert c.timeout == 7.0


def test_factory_selection(tmp_path: Path) -> None:
    m, mode = build_margaret({"MOCK_MARGARET": "1", "ANTHROPIC_API_KEY": "sk"})
    assert mode == "mock" and isinstance(m, MockMargaret)
    m, mode = build_margaret({"ANTHROPIC_API_KEY": ""})
    assert mode == "mock" and isinstance(m, MockMargaret)
    m, mode = build_margaret(
        {"ANTHROPIC_API_KEY": "sk", "DEMO_MODE": "1", "LLM_CACHE_DIR": str(tmp_path / "c")}
    )
    assert mode == "real" and isinstance(m, ClaudeMargaret)
    assert m.is_mock is False and m._cache.replay_only is True


def test_build_messages_truncates_player_text() -> None:
    msgs = build_messages([], "a" * 5000, 0.2)
    assert len(msgs[-1]["content"]) < 2200
