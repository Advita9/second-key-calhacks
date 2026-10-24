"""ClaudeExtractor against a fake client. Every failure path raises ExtractorError; the kernel
turns that into HOLD with X-00 (fail closed, CLAUDE.md I4)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import pytest
from pydantic import BaseModel

from kernel.llm.cache import ResponseCache
from kernel.llm.claude_extractor import ClaudeExtractor, make_client
from kernel.llm.schema import build_output_model
from kernel.llm.types import EvidenceItem, ExtractorError, ExtractorResult
from kernel.models import Outcome, PaymentIn, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.service import Kernel
from tests.factories import account_context, payment_in
from tests.unit.test_mock_extractor import load_case

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "extractor_s03.json"
RECORDED = json.loads(FIXTURE.read_text())


class FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.messages = FakeMessages(response, error)


def _conv_ids(conv: Sequence[EvidenceItem]) -> list[str]:
    return [e.id for e in conv]


def _response(conv: Sequence[EvidenceItem], *, stop_reason: str = "end_turn") -> Any:
    model = build_output_model(_conv_ids(conv))
    return SimpleNamespace(
        parsed_output=model.model_validate(RECORDED["parsed"]), stop_reason=stop_reason
    )


def _extractor(client: FakeClient, tmp_path: Path, *, replay_only: bool = False) -> ClaudeExtractor:
    return ClaudeExtractor(
        cast(anthropic.Anthropic, client),
        model="claude-test",
        cache=ResponseCache(tmp_path / "llm", replay_only=replay_only),
    )


@pytest.fixture
def s03() -> tuple[tuple[EvidenceItem, ...], PaymentIn]:
    return load_case("S-03")


def test_happy_path_returns_grounded_signals(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    client = FakeClient(_response(conv))
    res = _extractor(client, tmp_path).extract(conv, p)
    assert isinstance(res, ExtractorResult)
    assert res.signals
    by_id = {e.id: e for e in conv}
    for s in res.signals:
        assert s.evidence_span in by_id[s.source_id].text
    assert max(s.score for s in res.signals if s.kind == "secrecy") >= 0.7
    assert res.summary == RECORDED["parsed"]["summary"]


def test_parse_kwargs_are_minimal_and_never_include_sampling_params(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    client = FakeClient(_response(conv))
    _extractor(client, tmp_path).extract(conv, p)
    assert len(client.messages.calls) == 1
    kw = client.messages.calls[0]
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "tools", "tool_choice"):
        assert forbidden not in kw
    assert kw["model"] == "claude-test"
    assert kw["max_tokens"] == 1024
    assert isinstance(kw["system"], str) and "untrusted" in kw["system"].lower()
    assert kw["messages"][0]["role"] == "user"
    assert all(e.id in kw["messages"][0]["content"] for e in conv)
    assert issubclass(kw["output_format"], BaseModel)
    assert "output_config" not in kw


def test_effort_is_passed_only_when_set(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    client = FakeClient(_response(conv))
    ex = ClaudeExtractor(
        cast(anthropic.Anthropic, client),
        model="claude-test",
        cache=ResponseCache(tmp_path / "llm", replay_only=False),
        effort="low",
    )
    ex.extract(conv, p)
    assert client.messages.calls[0]["output_config"] == {"effort": "low"}


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_bad_stop_reason_raises(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path, stop_reason: str
) -> None:
    conv, p = s03
    client = FakeClient(_response(conv, stop_reason=stop_reason))
    with pytest.raises(ExtractorError):
        _extractor(client, tmp_path).extract(conv, p)
    assert list((tmp_path / "llm").glob("*.json")) == [] if (tmp_path / "llm").exists() else True


def test_client_exception_raises_extractor_error(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    client = FakeClient(error=RuntimeError("boom"))
    with pytest.raises(ExtractorError):
        _extractor(client, tmp_path).extract(conv, p)


def test_sdk_timeout_error_raises_extractor_error(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    client = FakeClient(error=anthropic.APITimeoutError(request=cast(Any, None)))
    with pytest.raises(ExtractorError):
        _extractor(client, tmp_path).extract(conv, p)


def test_parsed_output_none_raises(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    client = FakeClient(SimpleNamespace(parsed_output=None, stop_reason="end_turn"))
    with pytest.raises(ExtractorError):
        _extractor(client, tmp_path).extract(conv, p)


def test_foreign_source_id_raises(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03

    class Loose(BaseModel):
        signals: list[dict[str, Any]]
        summary: str

    parsed = Loose(
        signals=[{"kind": "secrecy", "score": 0.9, "source_id": "EV-9999", "evidence_span": "x"}],
        summary="s",
    )
    client = FakeClient(SimpleNamespace(parsed_output=parsed, stop_reason="end_turn"))
    with pytest.raises(ExtractorError):
        _extractor(client, tmp_path).extract(conv, p)


def test_non_substring_spans_are_dropped_not_fatal(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    conv, p = s03
    model = build_output_model(_conv_ids(conv))
    parsed = model.model_validate(
        {
            "signals": [
                {"kind": "secrecy", "score": 0.9, "source_id": "EV-0003", "evidence_span": "nope"},
                {
                    "kind": "secrecy",
                    "score": 0.9,
                    "source_id": "EV-0003",
                    "evidence_span": "Do not tell your bank",
                },
            ],
            "summary": "s",
        }
    )
    client = FakeClient(SimpleNamespace(parsed_output=parsed, stop_reason="end_turn"))
    res = _extractor(client, tmp_path).extract(conv, p)
    assert [s.evidence_span for s in res.signals] == ["Do not tell your bank"]


def test_empty_conversation_does_not_call_the_model(
    s03: tuple[tuple[EvidenceItem, ...], PaymentIn], tmp_path: Path
) -> None:
    _, p = s03
    client = FakeClient(error=AssertionError("must not be called"))
    assert _extractor(client, tmp_path).extract((), p).signals == ()


def test_kernel_fails_closed_to_hold_with_x00_when_extractor_raises(tmp_path: Path) -> None:
    conv, _ = load_case("S-03")
    client = FakeClient(error=RuntimeError("api down"))
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), extractor=_extractor(client, tmp_path))
    # Known biller under cap: would ALLOW on rules alone; must HOLD when the extractor fails.
    payment, decision = kernel.create_payment(payment_in(), account_context(), conv)
    assert decision.outcome is Outcome.HOLD
    assert "X-00" in decision.rule_ids
    assert payment.state is State.HELD
    kinds = [e.kind for e in kernel.get(payment.id).history]
    assert "EXTRACTOR_FAILED" in kinds


def test_kernel_with_working_extractor_records_signals(tmp_path: Path) -> None:
    conv, p = load_case("S-03")
    client = FakeClient(_response(conv))
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), extractor=_extractor(client, tmp_path))
    payment, decision = kernel.create_payment(p, account_context(mule_list=[]), conv)
    assert decision.outcome is Outcome.HOLD
    assert "H-02" in decision.rule_ids
    assert "X-00" not in decision.rule_ids
    assert kernel.get(payment.id).signals


def test_make_client_sets_timeout_and_no_retries() -> None:
    client = make_client("sk-test-not-real")
    assert client.max_retries == 0
    timeout = client.timeout
    read = getattr(timeout, "read", timeout)
    assert isinstance(read, float | int) and float(read) == 7.0
