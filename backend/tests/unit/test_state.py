"""State machine: every legal edge, no exits from DENIED or SUBMITTED, one writer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from kernel import certs
from kernel import state as sm
from kernel.audit import AuditLog
from kernel.clock import FakeClock
from kernel.db import connect, insert_payment, load_payment
from kernel.models import Capability, Outcome, Payment, State
from kernel.state import (
    Cancelled,
    Decided,
    EnteredReview,
    Event,
    HoldLifted,
    IllegalTransition,
    Mutated,
    Released,
    legal_edges,
    next_state,
    transition,
)
from tests.factories import payment, payment_in

KERNEL_DIR = Path(__file__).resolve().parents[2] / "kernel"


def _mutated(fp: str = "f" * 64) -> Mutated:
    return Mutated(new=payment_in(), new_fingerprint=fp, policy_version="v1")


def _ev(kind: type[Event]) -> Event:
    if kind is Decided:
        return Decided(outcome=Outcome.ALLOW, rule_ids=("A-01",))
    if kind is Released:
        return Released(certificate_id="cert_1", transfer_id="tr_1")
    if kind is Mutated:
        return _mutated()
    return kind()


def _consumed_cert(
    log: AuditLog, p: Payment, *, consumed: bool = True, fp: str | None = None
) -> str:
    """Insert a certificate row bound to `p` (or to `fp`) and optionally mark it consumed."""
    cert = certs.issue(
        log.conn,
        log._clock,  # noqa: SLF001
        payment=p if fp is None else p.model_copy(update={"fingerprint": fp}),
        actor_id="ops_1",
        capability=Capability.BANK_REVIEW,
        ttl_s=120,
    )
    if consumed:
        log.conn.execute(
            "UPDATE certificate SET consumed_at=? WHERE id=?",
            (log._clock.now().isoformat(), cert.id),  # noqa: SLF001
        )
    return cert.id


@pytest.fixture
def log(clock: FakeClock) -> AuditLog:
    return AuditLog(connect(":memory:"), clock)


def test_legal_edges_table() -> None:
    edges = legal_edges()
    assert (State.DRAFT, EnteredReview, State.PENDING_REVIEW) in edges
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
        for kind in (EnteredReview, Decided, HoldLifted, Released, Mutated, Cancelled):
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
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.ALLOW, rule_ids=("A-01",)))
    cert_id = _consumed_cert(log, p)
    p = _walk(log, p, Released(certificate_id=cert_id, transfer_id="tr_9"))
    assert p.state is State.SUBMITTED and p.nessie_transfer_id == "tr_9"
    stored = load_payment(log.conn, p.id)
    assert stored == p
    kinds = [e.kind for e in log.tail(10)]
    assert kinds == ["ENTERED_REVIEW", "DECIDED", "RELEASED"]
    decided = log.tail(10)[1].payload
    assert decided["event"] == {"outcome": "ALLOW", "rule_ids": ["A-01"]}
    assert decided["from_fingerprint"] == decided["fingerprint"] == p.fingerprint
    assert log.verify().ok


def test_released_requires_consumed_certificate_row(log: AuditLog) -> None:
    """I1 at the chokepoint: no consumed, unvoided cert bound to this fingerprint, no SUBMITTED."""
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.ALLOW, rule_ids=()))
    with pytest.raises(IllegalTransition):  # no cert at all
        transition(p, Released(certificate_id="cert_ghost", transfer_id="t"), audit=log, actor="t")
    unconsumed = _consumed_cert(log, p, consumed=False)
    with pytest.raises(IllegalTransition):  # issued but not consumed
        transition(p, Released(certificate_id=unconsumed, transfer_id="t"), audit=log, actor="t")
    other_fp = _consumed_cert(log, p, fp="e" * 64)
    with pytest.raises(IllegalTransition):  # consumed, but bound to another fingerprint
        transition(p, Released(certificate_id=other_fp, transfer_id="t"), audit=log, actor="t")
    voided = _consumed_cert(log, p)
    log.conn.execute(
        "UPDATE certificate SET voided_at='2026-01-01T00:00:00+00:00' WHERE id=?", (voided,)
    )
    with pytest.raises(IllegalTransition):  # consumed but voided
        transition(p, Released(certificate_id=voided, transfer_id="t"), audit=log, actor="t")
    assert load_payment(log.conn, p.id).state is State.ELIGIBLE_TO_SUBMIT
    assert log.verify().ok and log.verify().length == 2
    good = _consumed_cert(log, p)
    assert (
        transition(p, Released(certificate_id=good, transfer_id="t"), audit=log, actor="t").state
        is State.SUBMITTED
    )


def test_hold_then_lift(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.HOLD, rule_ids=("H-01",)))
    assert p.state is State.HELD
    p = _walk(log, p, HoldLifted())
    assert p.state is State.ELIGIBLE_TO_SUBMIT


def test_mutated_resets_to_pending_and_changes_fingerprint(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.ALLOW, rule_ids=()))
    old = p.fingerprint
    new_in = payment_in(amount_cents=123)
    p = _walk(log, p, Mutated(new=new_in, new_fingerprint="a" * 64, policy_version="v9"))
    assert p.state is State.PENDING_REVIEW and p.fingerprint == "a" * 64 != old
    assert p.amount_cents == 123 and p.policy_version == "v9"
    stored = load_payment(log.conn, p.id)
    assert stored == p and stored.fingerprint == "a" * 64
    ev = log.tail(1)[0].payload
    assert ev["from_fingerprint"] == old and ev["fingerprint"] == "a" * 64
    event = cast(dict[str, Any], ev["event"])
    assert event["new"]["amount_cents"] == 123


def test_stale_fingerprint_handle_cannot_transition_or_revert(log: AuditLog) -> None:
    """A3: the UPDATE is pinned to (id, state, fingerprint); a stale handle cannot revert F2."""
    p0 = payment()
    insert_payment(log.conn, p0)
    p1 = _walk(log, p0, EnteredReview())
    p2 = _walk(log, p1, _mutated("b" * 64))  # PENDING_REVIEW, fingerprint F2
    stale = p2.model_copy(update={"fingerprint": p1.fingerprint})  # same state, old fingerprint
    with pytest.raises(IllegalTransition):
        transition(stale, Decided(outcome=Outcome.ALLOW, rule_ids=()), audit=log, actor="t")
    with pytest.raises(IllegalTransition):
        transition(stale, _mutated("c" * 64), audit=log, actor="t")
    stored = load_payment(log.conn, p2.id)
    assert stored.fingerprint == "b" * 64 and stored.state is State.PENDING_REVIEW


def test_non_mutation_events_never_touch_fingerprint_or_fields(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.HOLD, rule_ids=()), HoldLifted())
    stored = load_payment(log.conn, p.id)
    assert stored.fingerprint == p.fingerprint and stored.amount_cents == 800_000


def test_insert_payment_requires_draft(log: AuditLog) -> None:
    """A2: a payment can only be born DRAFT; every other state is reached by a transition."""
    for s in State:
        if s is State.DRAFT:
            continue
        with pytest.raises(ValueError):
            insert_payment(log.conn, payment(state=s, pid=f"pay_{s.value}"))
    with pytest.raises(ValueError):
        insert_payment(log.conn, payment().model_copy(update={"nessie_transfer_id": "tr_x"}))
    assert log.conn.execute("SELECT count(*) FROM payment").fetchone()[0] == 0


def test_event_fields_are_validated() -> None:
    with pytest.raises(ValidationError):
        Mutated(new=payment_in(), new_fingerprint="not-hex", policy_version="v1")
    with pytest.raises(ValidationError):
        Mutated(new=payment_in(), new_fingerprint="A" * 64, policy_version="v1")  # upper case
    with pytest.raises(ValidationError):
        Mutated(new=payment_in(), new_fingerprint="a" * 64, policy_version="")
    with pytest.raises(ValidationError):
        Released(certificate_id="", transfer_id="t")
    with pytest.raises(ValidationError):
        Released(certificate_id="c", transfer_id="")
    with pytest.raises(ValidationError):
        Decided(outcome="ALLOW", rule_ids=())  # type: ignore[arg-type]


def test_illegal_transition_raises_and_leaves_row_untouched(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.DENY, rule_ids=("D-01",)))
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
    p1 = transition(p0, EnteredReview(), audit=log, actor="test")
    assert p1.state is State.PENDING_REVIEW
    with pytest.raises(IllegalTransition):
        transition(p0, EnteredReview(), audit=log, actor="test")


def test_transition_requires_known_payment(log: AuditLog) -> None:
    with pytest.raises(IllegalTransition):
        transition(payment(), EnteredReview(), audit=log, actor="test")


def test_payment_model_is_frozen() -> None:
    p = payment()
    with pytest.raises(Exception):  # noqa: B017  pydantic ValidationError on frozen instance
        p.state = State.SUBMITTED  # type: ignore[misc]


# Any of these outside state.py means someone is writing payment state behind the chokepoint.
_MUTATION_PATTERNS = [
    re.compile(r"\.state\s*=[^=]"),
    re.compile(r"model_copy\("),
    re.compile(r"model_construct\("),
    re.compile(r"\bsetattr\("),
    re.compile(r"__dict__"),
    re.compile(r"__setattr__"),
    re.compile(r"\bREPLACE\s+INTO\s+payment\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+payment\b", re.IGNORECASE),
]
# INSERT INTO payment only in db.py; constructing a non-DRAFT State only in state/models/db.
_INSERT = re.compile(r"\bINSERT\s+INTO\s+payment\b", re.IGNORECASE)
_NON_DRAFT_STATE = re.compile(
    r"\bstate\s*=\s*State\.(?!DRAFT\b)|[\"']state[\"']\s*:\s*State\.(?!DRAFT\b)|\bState\("
)
# Folders outside the payment path (room, voice, persona) are other lanes' code and do not
# touch Payment; everything else under kernel/ is scanned.
_SKIP = ("voice", "margaret", "room_memory.py")


def _kernel_files() -> list[Path]:
    return [
        p
        for p in KERNEL_DIR.rglob("*.py")
        if not any(part in _SKIP for part in p.relative_to(KERNEL_DIR).parts)
    ]


def test_state_py_is_the_only_writer() -> None:
    offenders: list[str] = []
    for path in _kernel_files():
        rel = str(path.relative_to(KERNEL_DIR))
        src = path.read_text()
        if path.name != "state.py":
            for pat in _MUTATION_PATTERNS:
                if pat.search(src):
                    offenders.append(f"{rel}: {pat.pattern}")
        if path.name != "db.py" and _INSERT.search(src):
            offenders.append(f"{rel}: INSERT INTO payment")
        if path.name not in ("state.py", "models.py", "db.py") and _NON_DRAFT_STATE.search(src):
            offenders.append(f"{rel}: constructs a non-DRAFT State")
    assert offenders == []
    state_src = Path(str(sm.__file__)).read_text()
    assert any(pat.search(state_src) for pat in _MUTATION_PATTERNS)


def test_released_rejects_consumed_but_expired_row(log: AuditLog) -> None:
    p = payment()
    insert_payment(log.conn, p)
    p = _walk(log, p, EnteredReview(), Decided(outcome=Outcome.ALLOW, rule_ids=()))
    cert_id = _consumed_cert(log, p)
    # Forge a row that was "consumed" after its expiry: the chokepoint must not accept it.
    log.conn.execute(
        "UPDATE certificate SET consumed_at=? WHERE id=?",
        ("2099-01-01T00:00:00+00:00", cert_id),
    )
    with pytest.raises(IllegalTransition):
        transition(p, Released(certificate_id=cert_id, transfer_id="t"), audit=log, actor="t")
    assert load_payment(log.conn, p.id).state is State.ELIGIBLE_TO_SUBMIT
