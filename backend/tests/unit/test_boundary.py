"""I4: the model layer cannot reach state transitions except through the policy engine."""

from __future__ import annotations

import ast
import re
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


_MODEL_LAYER_FORBIDDEN = (
    "kernel.state",
    "kernel.service",
    "kernel.certs",
    "kernel.attest",
    "kernel.db",
    "kernel.audit",
    "kernel.fingerprint",
    "kernel.policy",
    "kernel.rail",
)
_DYNAMIC_IMPORT = re.compile(r"\bimportlib\b|__import__|\bexec\(|\beval\(")


def test_model_layer_imports_nothing_that_can_move_state() -> None:
    """kernel/llm and kernel/margaret may only see models and their own package."""
    for folder in ("llm", "margaret"):
        for path in (KERNEL_DIR / folder).rglob("*.py"):
            bad = {m for m in _imports(path) if m.startswith(_MODEL_LAYER_FORBIDDEN)}
            assert bad == set(), f"{folder}/{path.name} imports {bad}"
            assert not _DYNAMIC_IMPORT.search(path.read_text()), f"{folder}/{path.name}"


def test_decided_is_constructed_only_in_state_and_service() -> None:
    """Call-site check: the only `Decided(` builders are the class itself and the facade,
    and the facade always takes the outcome from a policy Decision."""
    hits: dict[str, list[str]] = {}
    for path in KERNEL_DIR.rglob("*.py"):
        for line in path.read_text().splitlines():
            if "Decided(" in line and not line.lstrip().startswith("#"):
                hits.setdefault(str(path.relative_to(KERNEL_DIR)), []).append(line.strip())
    assert set(hits) == {"state.py", "service.py"}, hits
    assert hits["state.py"] == ["class Decided(Event):"]
    assert all("outcome=decision.outcome" in line for line in hits["service.py"]), hits


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


# ---- Margaret persona layer (T6) -----------------------------------------------------------


def test_margaret_imports_nothing_from_state_or_service() -> None:
    forbidden = ("kernel.state", "kernel.service", "kernel.certs", "kernel.attest", "kernel.db")
    for path in (KERNEL_DIR / "margaret").glob("*.py"):
        bad = {m for m in _imports(path) if m.startswith(forbidden)}
        assert bad == set(), f"{path.name} imports {bad}"


def test_state_and_service_import_nothing_from_margaret() -> None:
    for name in ("state.py", "service.py"):
        mods = _imports(KERNEL_DIR / name)
        assert not {m for m in mods if m.startswith("kernel.margaret")}, name


def test_margaret_turn_has_no_kernel_state_typed_field() -> None:
    from typing import get_args, get_origin

    from kernel.margaret.types import DraftPayment, MargaretTurn
    from kernel.models import Decision, State
    from kernel.state import Event

    banned: tuple[type, ...] = (Event, Decision, State, Decided)

    def leaves(tp: object) -> set[object]:
        args = get_args(tp)
        if not args:
            return {tp}
        out: set[object] = set()
        if get_origin(tp) is not None:
            out.add(get_origin(tp))
        for a in args:
            out |= leaves(a)
        return out

    for model in (MargaretTurn, DraftPayment):
        for name, field in model.model_fields.items():
            for leaf in leaves(field.annotation):
                for b in banned:
                    assert not (isinstance(leaf, type) and issubclass(leaf, b)), (model, name)
