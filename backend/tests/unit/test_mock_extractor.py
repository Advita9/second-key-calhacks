"""MockExtractor: heuristic signals with real evidence ids and exact spans. Never reads labels."""

from __future__ import annotations

import json
from pathlib import Path

from kernel.llm.mock_extractor import MockExtractor
from kernel.llm.types import EvidenceItem, ExtractorResult
from kernel.models import PaymentIn

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"


def load_case(case_id: str) -> tuple[tuple[EvidenceItem, ...], PaymentIn]:
    raw = json.loads((CASES / f"{case_id}.json").read_text())
    conv = tuple(EvidenceItem.model_validate(e) for e in raw["conversation"])
    p = PaymentIn.model_validate({**raw["payment"], "conversation_id": case_id}, strict=False)
    return conv, p


def _by_kind(res: ExtractorResult, kind: str) -> list[float]:
    return [s.score for s in res.signals if s.kind == kind]


def _assert_grounded(res: ExtractorResult, conv: tuple[EvidenceItem, ...]) -> None:
    by_id = {e.id: e for e in conv}
    for s in res.signals:
        assert s.source_id in by_id
        assert s.evidence_span in by_id[s.source_id].text
        assert by_id[s.source_id].speaker != "margaret"


def test_s03_secrecy_and_authority_with_real_ids_and_spans() -> None:
    conv, p = load_case("S-03")
    res = MockExtractor().extract(conv, p)
    _assert_grounded(res, conv)
    assert max(_by_kind(res, "secrecy")) >= 0.7
    assert _by_kind(res, "authority")
    secrecy = next(s for s in res.signals if s.kind == "secrecy")
    assert secrecy.source_id == "EV-0003"
    assert secrecy.evidence_span == "Do not tell your bank"
    authority = next(s for s in res.signals if s.kind == "authority")
    assert authority.source_id == "EV-0001"


def test_s05_secrecy() -> None:
    conv, p = load_case("S-05")
    res = MockExtractor().extract(conv, p)
    _assert_grounded(res, conv)
    assert max(_by_kind(res, "secrecy")) >= 0.7


def test_l11_has_no_secrecy_and_no_strong_urgency() -> None:
    conv, p = load_case("L-11")
    res = MockExtractor().extract(conv, p)
    _assert_grounded(res, conv)
    assert _by_kind(res, "secrecy") == []
    urgency = _by_kind(res, "urgency")
    assert not urgency or max(urgency) < 0.8


def test_margaret_only_conversation_yields_nothing() -> None:
    conv = (
        EvidenceItem(id="EV-0001", speaker="margaret", text="Do not tell your bank, he said."),
        EvidenceItem(id="EV-0002", speaker="Margaret", text="This is Agent Daniels with the IRS."),
    )
    _, p = load_case("S-03")
    res = MockExtractor().extract(conv, p)
    assert res.signals == ()
    assert isinstance(res, ExtractorResult)


def test_empty_conversation() -> None:
    _, p = load_case("S-03")
    assert MockExtractor().extract((), p).signals == ()


def test_warmth_never_becomes_a_signal() -> None:
    conv = (EvidenceItem(id="EV-0001", speaker="caller", text="Good morning my darling."),)
    _, p = load_case("S-05")
    assert all(str(s.kind) != "warmth" for s in MockExtractor().extract(conv, p).signals)


def test_module_never_reads_tags_or_expected() -> None:
    src = Path(MockExtractor.__module__.replace(".", "/") + ".py")
    root = Path(__file__).resolve().parents[2]
    text = (root / src).read_text()
    for word in ("tags", "expected", "fixtures", "signals_required"):
        assert word not in text, word
