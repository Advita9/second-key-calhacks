"""I4: the model layer cannot reach state transitions except through the policy engine."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from kernel.llm.types import ExtractorResult, NullExtractor, Signal
from kernel.models import Outcome
from kernel.state import Decided
from tests.factories import payment_in

KERNEL_DIR = Path(__file__).resolve().parents[2] / "kernel"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_llm_layer_imports_nothing_from_state_or_service() -> None:
    forbidden = ("kernel.state", "kernel.service", "kernel.certs", "kernel.attest", "kernel.db")
    for path in (KERNEL_DIR / "llm").glob("*.py"):
        bad = {m for m in _imports(path) if m.startswith(forbidden)}
        assert bad == set(), f"{path.name} imports {bad}"


def test_state_imports_nothing_from_llm_or_policy() -> None:
    mods = _imports(KERNEL_DIR / "state.py")
    assert not {m for m in mods if m.startswith(("kernel.llm", "kernel.policy"))}


def test_policy_engine_imports_nothing_from_state_or_db() -> None:
    for path in (KERNEL_DIR / "policy").glob("*.py"):
        mods = _imports(path)
        assert not {
            m for m in mods if m.startswith(("kernel.state", "kernel.db", "kernel.audit"))
        }, path.name


def test_decided_cannot_be_built_from_extractor_output() -> None:
    result = ExtractorResult(
        signals=(Signal(kind="urgency", score=0.9, source_id="EV-1", evidence_span="now"),),
        summary="x",
    )
    with pytest.raises(ValidationError):
        Decided(outcome=result, rule_ids=())  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Decided(outcome="ALLOW", rule_ids=())  # type: ignore[arg-type]
    assert Decided(outcome=Outcome.ALLOW, rule_ids=()).outcome is Outcome.ALLOW


def test_signal_is_strict() -> None:
    with pytest.raises(ValidationError):
        Signal(kind="vibes", score=0.5, source_id="EV-1", evidence_span="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Signal(kind="urgency", score=1.5, source_id="EV-1", evidence_span="x")
    with pytest.raises(ValidationError):
        Signal(kind="urgency", score="0.5", source_id="EV-1", evidence_span="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Signal.model_validate(
            {"kind": "urgency", "score": 0.5, "source_id": "EV-1", "evidence_span": "x", "extra": 1}
        )


def test_null_extractor_emits_nothing() -> None:
    r = NullExtractor().extract([], payment_in())
    assert r.signals == () and r.summary == ""
