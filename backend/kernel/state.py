"""Payment state machine. `transition()` is the only code that writes Payment.state.

`next_state()` is pure. `transition()` persists the new row and appends the audit event in
one write transaction. Nothing else in the kernel may assign `.state`, `UPDATE ... SET state`,
or `model_copy(update={"state": ...})`; `tests/unit/test_state.py` greps for it.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

from kernel.audit import AuditLog
from kernel.db import immediate
from kernel.models import Outcome, Payment, State

log = logging.getLogger("second_key.state")


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class Submitted(Event):
    """DRAFT -> PENDING_REVIEW. The payment entered review."""


class Decided(Event):
    """PENDING_REVIEW -> ELIGIBLE_TO_SUBMIT | HELD | DENIED. Built only from a policy Decision."""

    outcome: Outcome
    rule_ids: tuple[str, ...]


class HoldLifted(Event):
    """HELD -> ELIGIBLE_TO_SUBMIT. BANK_REVIEW only (enforced by the caller, I6)."""


class Released(Event):
    """ELIGIBLE_TO_SUBMIT -> SUBMITTED. Requires a verified, consumed certificate (I1)."""

    certificate_id: str
    transfer_id: str


class Mutated(Event):
    """Any pre-settlement state -> PENDING_REVIEW with a new fingerprint (I2)."""

    new_fingerprint: str


class Cancelled(Event):
    """Any pre-settlement state -> CANCELLED."""


class IllegalTransition(Exception):
    def __init__(self, state: State, event: Event, reason: str = "") -> None:
        self.state = state
        self.event = event
        msg = f"{type(event).__name__} not allowed from {state.value}"
        super().__init__(f"{msg}: {reason}" if reason else msg)


_PRE_SETTLEMENT: tuple[State, ...] = (State.PENDING_REVIEW, State.HELD, State.ELIGIBLE_TO_SUBMIT)

# Fixed edges. DENIED, SUBMITTED and CANCELLED are terminal: no row starts from them.
TRANSITIONS: dict[tuple[State, type[Event]], State] = {
    (State.DRAFT, Submitted): State.PENDING_REVIEW,
    (State.HELD, HoldLifted): State.ELIGIBLE_TO_SUBMIT,
    (State.ELIGIBLE_TO_SUBMIT, Released): State.SUBMITTED,
    **{(s, Mutated): State.PENDING_REVIEW for s in _PRE_SETTLEMENT},
    **{(s, Cancelled): State.CANCELLED for s in (State.DRAFT, *_PRE_SETTLEMENT)},
}

# The one data-dependent edge: a Decision picks the target from PENDING_REVIEW.
DECISION_TARGETS: dict[Outcome, State] = {
    Outcome.ALLOW: State.ELIGIBLE_TO_SUBMIT,
    Outcome.HOLD: State.HELD,
    Outcome.DENY: State.DENIED,
}


def legal_edges() -> frozenset[tuple[State, type[Event], State]]:
    fixed = {(s, e, t) for (s, e), t in TRANSITIONS.items()}
    decided = {(State.PENDING_REVIEW, Decided, t) for t in DECISION_TARGETS.values()}
    return frozenset(fixed | decided)


def next_state(state: State, ev: Event) -> State:
    """Pure: the target state for (state, event), or IllegalTransition."""
    if isinstance(ev, Decided):
        if state is not State.PENDING_REVIEW:
            raise IllegalTransition(state, ev)
        return DECISION_TARGETS[ev.outcome]
    try:
        return TRANSITIONS[(state, type(ev))]
    except KeyError:
        raise IllegalTransition(state, ev) from None


def transition(p: Payment, ev: Event, *, audit: AuditLog, actor: str) -> Payment:
    """Apply `ev` to `p`: validate, persist the row (optimistic on current state), audit."""
    target = next_state(p.state, ev)
    updates: dict[str, object] = {"state": target}
    if isinstance(ev, Mutated):
        updates["fingerprint"] = ev.new_fingerprint
    if isinstance(ev, Released):
        updates["nessie_transfer_id"] = ev.transfer_id
    new = p.model_copy(update=updates)

    with immediate(audit.conn):
        cur = audit.conn.execute(
            "UPDATE payment SET state=?, fingerprint=?, nessie_transfer_id=? "
            "WHERE id=? AND state=?",
            (new.state.value, new.fingerprint, new.nessie_transfer_id, p.id, p.state.value),
        )
        if cur.rowcount != 1:
            raise IllegalTransition(p.state, ev, "payment row missing or stale")
        payload: dict[str, object] = {
            "payment_id": p.id,
            "from": p.state.value,
            "to": target.value,
            "fingerprint": new.fingerprint,
            **ev.model_dump(mode="json"),
        }
        audit.append(actor, _kind(ev), payload)
    log.info(
        "state.transition",
        extra={"payment_id": p.id, "from": p.state.value, "to": target.value, "event": _kind(ev)},
    )
    return new


def _kind(ev: Event) -> str:
    name = type(ev).__name__
    return "".join(("_" + c if c.isupper() and i else c) for i, c in enumerate(name)).upper()
