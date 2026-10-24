"""Per-request output model and the defensive sanitizer (I4: model output is data, not trusted)."""

from __future__ import annotations

import math
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from kernel.llm.schema import build_output_model, sanitize
from kernel.llm.types import SIGNAL_KINDS, EvidenceItem, ExtractorError, ExtractorResult

EVIDENCE = (
    EvidenceItem(id="EV-0001", speaker="caller", text="This is Agent Daniels with the IRS."),
    EvidenceItem(id="EV-0003", speaker="caller", text="Do not tell your bank or your daughter."),
)


def _sig(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "kind": "secrecy",
        "score": 0.9,
        "source_id": "EV-0003",
        "evidence_span": "Do not tell your bank",
    }
    base.update(over)
    return base


def test_literal_model_rejects_foreign_source_id() -> None:
    model = build_output_model(["EV-0001", "EV-0003"])
    ok = model.model_validate({"signals": [_sig()], "summary": "s"})
    assert ok.model_dump()["signals"][0]["source_id"] == "EV-0003"
    with pytest.raises(ValidationError):
        model.model_validate({"signals": [_sig(source_id="EV-9999")], "summary": "s"})
    with pytest.raises(ValidationError):
        model.model_validate({"signals": [_sig(kind="vibes")], "summary": "s"})


def test_schema_enumerates_ids() -> None:
    schema = build_output_model(["EV-0001", "EV-0003"]).model_json_schema()
    assert "EV-0001" in str(schema) and "EV-0003" in str(schema)
    assert "EV-9999" not in str(schema)


def test_empty_ids_raise() -> None:
    with pytest.raises(ExtractorError):
        build_output_model([])


def test_sanitize_drops_non_substring_span() -> None:
    out = sanitize({"signals": [_sig(evidence_span="tell your mother")]}, EVIDENCE)
    assert out.signals == ()


def test_sanitize_span_must_match_the_cited_item_not_any_item() -> None:
    out = sanitize({"signals": [_sig(source_id="EV-0001")]}, EVIDENCE)
    assert out.signals == ()


def test_sanitize_drops_foreign_id_and_unknown_kind() -> None:
    out = sanitize({"signals": [_sig(source_id="EV-7777"), _sig(kind="vibes"), _sig()]}, EVIDENCE)
    assert len(out.signals) == 1
    assert out.signals[0].source_id == "EV-0003"


def test_sanitize_clamps_scores() -> None:
    out = sanitize({"signals": [_sig(score=1.7), _sig(score=-3), _sig(score=1)]}, EVIDENCE)
    assert [s.score for s in out.signals] == [1.0, 0.0, 1.0]
    assert sanitize({"signals": [_sig(score=math.nan)]}, EVIDENCE).signals == ()
    assert sanitize({"signals": [_sig(score=True)]}, EVIDENCE).signals == ()
    assert sanitize({"signals": [_sig(score="0.9")]}, EVIDENCE).signals == ()


def test_sanitize_caps_at_max_signals() -> None:
    out = sanitize({"signals": [_sig()] * 40}, EVIDENCE)
    assert len(out.signals) == 12
    assert len(sanitize({"signals": [_sig()] * 40}, EVIDENCE, max_signals=3).signals) == 3


def test_sanitize_summary_is_string_or_empty() -> None:
    assert sanitize({"summary": 5}, EVIDENCE).summary == ""
    assert sanitize({"summary": "x" * 2000}, EVIDENCE).summary == "x" * 500
    assert sanitize({"summary": "fine"}, EVIDENCE).summary == "fine"


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"signals": None},
        {"signals": "nope"},
        {"signals": [None, 1, "x", [], {}]},
        {"signals": [{"kind": None, "score": None, "source_id": None, "evidence_span": None}]},
        {"signals": [{"kind": "secrecy"}]},
        {"signals": {"kind": "secrecy"}},
        {"summary": None, "signals": [_sig(evidence_span="")]},
    ],
)
def test_sanitize_never_raises_on_garbage(raw: dict[str, Any]) -> None:
    out = sanitize(raw, EVIDENCE)
    assert isinstance(out, ExtractorResult)


_json = st.recursive(
    st.none() | st.booleans() | st.floats() | st.integers() | st.text(max_size=20),
    lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=8), c, max_size=4),
    max_leaves=12,
)


@given(st.dictionaries(st.sampled_from(["signals", "summary", "x"]), _json, max_size=3))
def test_sanitize_never_raises_property(raw: dict[str, Any]) -> None:
    out = sanitize(raw, EVIDENCE)
    for s in out.signals:
        assert s.kind in SIGNAL_KINDS
        assert 0.0 <= s.score <= 1.0
        item = next(e for e in EVIDENCE if e.id == s.source_id)
        assert s.evidence_span and s.evidence_span in item.text
