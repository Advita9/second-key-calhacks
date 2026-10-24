"""State machine: every legal edge, no exits from DENIED or SUBMITTED, one writer."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kernel import state as sm
from kernel.audit import AuditLog
from kernel.clock import FakeClock
from kernel.db import connect, insert_payment, load_payment
from kernel.models import Outcome, Payment, State
from kernel.state import (
    Cancelled,
    Decided,
    Event,
    HoldLifted,
    IllegalTransition,
    Mutated,
    Released,
    Submitted,
    legal_edges,
    next_state,
    transition,
)
from tests.factories import payment

KERNEL_DIR = Path(__file__).resolve().parents[2] / "kernel"


def _ev(kind: type[Event]) -> Event:
    if kind is Decided:
        return Decided(outcome=Outcome.ALLOW, rule_ids=("A-01",))
    if kind is Released:
        return Released(certificate_id="cert_1", transfer_id="tr_1")
    if kind is Mutated:
        return Mutated(new_fingerprint="f" * 64)
    return kind()


@pytest.fixture
def log(clock: FakeClock) -> AuditLog:
    return AuditLog(connect(":memory:"), clock)


def test_legal_edges_table() -> None:
    edges = legal_edges()
    assert (State.DRAFT, Submitted, State.PENDING_REVIEW) in edges
    assert (State.PENDING_REVIEW, Decided, State.ELIGIBLE_TO_SUBMIT) in edges
    assert (State.PENDING_REVIEW, Decided, State.HELD) in edges
    assert (State.PENDING_REVIEW, Decided, State.DENIED) in edges
    assert (State.HELD, HoldLifted, State.ELIGIBLE_TO_SUBMIT) in edges
    assert (State.ELIGIBLE_TO_SUBMIT, Released, State.SUBMITTED) in edges
    for s in (State.PENDING_REVIEW, State.HELD, State.ELIGIBLE_TO_SUBMIT):
        assert (s, Mutated, State.PENDING_REVIEW) in edges
        assert (s, Cancelled, State.CANCELLED) in edges


def test_denied_submitted_cancelled_have_no_outgoing_edges() -> None:
    for s in (State.DENIED, State.SUBMITTED, State.CANCELLED):
        assert not [e for e in legal_edges() if e[0] == s]
        for kind in (Submitted, Decided, HoldLifted, Released, Mutated, Cancelled):
            with pytest.raises(IllegalTransition):
                next_state(s, _ev(kind))


@pytest.mark.parametrize(
    ("outcome", "target"),
    [
        (Outcome.ALLOW, State.ELIGIBLE_TO_SUBMIT),
        (Outcome.HOLD, State.HELD),
        (Outcome.DENY, State.DENIED),
    ],
)
def test_decided_maps_outcome(outcome: Outcome, target: State) -> None:
    assert next_state(State.PENDING_REVIEW, Decided(outcome=outcome, rule_ids=())) == target


def test_decided_only_from_pending_review() -> None:
    for s in State:
        if s is State.PENDING_REVIEW:
            continue
        with pytest.raises(IllegalTransition):
            next_state(s, Decided(outcome=Outcome.ALLOW, rule_ids=()))


def test_hold_cannot_be_lifted_from_other_states() -> None:
    for s in State:
        if s is State.HELD:
            continue
        with pytest.raises(IllegalTransition):
            next_state(s, HoldLifted())


def test_released_only_from_eligible() -> None:
    for s in State:
        if s is State.ELIGIBLE_TO_SUBMIT:
            continue
        with pytest.raises(IllegalTransition):
            next_state(s, Released(certificate_id="c", transfer_id="t"))


def _walk(log: AuditLog, p: Payment, *events: Event) -> Payment:
    for ev in events:
        p = transition(p, ev, audit=log, actor="test")
    return p


def test_full_happy_path_persists_and_audits(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(
        log,
        p,
        Submitted(),
        Decided(outcome=Outcome.ALLOW, rule_ids=("A-01",)),
        Released(certificate_id="cert_1", transfer_id="tr_9"),
    )
    assert p.state is State.SUBMITTED and p.nessie_transfer_id == "tr_9"
    stored = load_payment(log.conn, p.id)
    assert stored == p
    kinds = [e.kind for e in log.tail(10)]
    assert kinds == ["SUBMITTED", "DECIDED", "RELEASED"]
    assert log.tail(10)[1].payload["rule_ids"] == ["A-01"]
    assert log.verify().ok


def test_hold_then_lift(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, Submitted(), Decided(outcome=Outcome.HOLD, rule_ids=("H-01",)))
    assert p.state is State.HELD
    p = _walk(log, p, HoldLifted())
    assert p.state is State.ELIGIBLE_TO_SUBMIT


def test_mutated_resets_to_pending_and_changes_fingerprint(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, Submitted(), Decided(outcome=Outcome.ALLOW, rule_ids=()))
    old = p.fingerprint
    p = _walk(log, p, Mutated(new_fingerprint="a" * 64))
    assert p.state is State.PENDING_REVIEW and p.fingerprint == "a" * 64 != old
    assert load_payment(log.conn, p.id).fingerprint == "a" * 64


def test_illegal_transition_raises_and_leaves_row_untouched(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, Submitted(), Decided(outcome=Outcome.DENY, rule_ids=("D-01",)))
    with pytest.raises(IllegalTransition):
        transition(p, HoldLifted(), audit=log, actor="test")
    with pytest.raises(IllegalTransition):
        transition(p, Released(certificate_id="c", transfer_id="t"), audit=log, actor="test")
    assert load_payment(log.conn, p.id).state is State.DENIED
    assert log.verify().length == 2


def test_stale_payment_object_is_rejected(log: AuditLog) -> None:
    """Two in-memory copies: the second write must fail instead of silently overwriting."""
    p0 = payment()
    insert_payment(log.conn, p0)
    p1 = transition(p0, Submitted(), audit=log, actor="test")
    assert p1.state is State.PENDING_REVIEW
    with pytest.raises(IllegalTransition):
        transition(p0, Submitted(), audit=log, actor="test")


def test_transition_requires_known_payment(log: AuditLog) -> None:
    with pytest.raises(IllegalTransition):
        transition(payment(), Submitted(), audit=log, actor="test")


def test_payment_model_is_frozen() -> None:
    p = payment()
    with pytest.raises(Exception):  # noqa: B017  pydantic ValidationError on frozen instance
        p.state = State.SUBMITTED  # type: ignore[misc]


_MUTATION_PATTERNS = [
    re.compile(r"\.state\s*=[^=]"),
    re.compile(r"update\s*=\s*\{[^}]*[\"']state[\"']"),
    re.compile(r"__setattr__\([^)]*[\"']state[\"']"),
    re.compile(r"\bSET\b[^;]*\bstate\s*=", re.IGNORECASE),
]


def test_state_py_is_the_only_writer() -> None:
    offenders: list[str] = []
    for path in KERNEL_DIR.rglob("*.py"):
        if path.name == "state.py":
            continue
        src = path.read_text()
        for pat in _MUTATION_PATTERNS:
            if pat.search(src):
                offenders.append(f"{path.relative_to(KERNEL_DIR)}: {pat.pattern}")
    assert offenders == []
    state_src = Path(str(sm.__file__)).read_text()
    assert any(pat.search(state_src) for pat in _MUTATION_PATTERNS)
