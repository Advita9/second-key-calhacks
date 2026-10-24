"""Payment state machine. `transition()` is the only code that writes Payment.state.

`next_state()` is pure. `transition()` persists the new row and appends the audit event in
one write transaction. The UPDATE is pinned to the caller's (id, state, fingerprint), so a
stale handle can neither move the state nor revert a fingerprint. Only `Mutated` rewrites
the money fields and the fingerprint. `Released` additionally requires a consumed,
unvoided certificate bound to the current fingerprint to exist in the same transaction (I1).

Nothing else in the kernel may assign `.state`, build a non-DRAFT `State`, `model_copy` a
payment, or `UPDATE payment`; `tests/unit/test_state.py` greps for it.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from kernel.audit import AuditLog
from kernel.db import immediate
from kernel.models import Outcome, Payment, PaymentIn, State

log = logging.getLogger("second_key.state")

_HEX64 = r"^[0-9a-f]{64}$"


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class EnteredReview(Event):
    """DRAFT -> PENDING_REVIEW. The payment entered review."""


class Decided(Event):
    """PENDING_REVIEW -> ELIGIBLE_TO_SUBMIT | HELD | DENIED. Built only from a policy Decision."""

    outcome: Outcome
    rule_ids: tuple[str, ...]


class HoldLifted(Event):
    """HELD -> ELIGIBLE_TO_SUBMIT. BANK_REVIEW only (enforced by the caller, I6)."""


class Released(Event):
    """ELIGIBLE_TO_SUBMIT -> SUBMITTED. Requires a consumed certificate row (I1)."""

    certificate_id: str = Field(min_length=1)
    transfer_id: str = Field(min_length=1)


class Mutated(Event):
    """Any pre-settlement state -> PENDING_REVIEW with new fields and a new fingerprint (I2)."""

    new: PaymentIn
    new_fingerprint: str = Field(pattern=_HEX64)
    policy_version: str = Field(min_length=1)


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
    (State.DRAFT, EnteredReview): State.PENDING_REVIEW,
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
    """Apply `ev` to `p`: validate, persist (pinned to id, state, fingerprint), audit."""
    target = next_state(p.state, ev)
    conn = audit.conn
    with immediate(conn):
        if isinstance(ev, Released):
            bound = conn.execute(
                "SELECT 1 FROM certificate WHERE id=? AND payment_id=? AND fingerprint=? "
                "AND voided_at IS NULL AND consumed_at IS NOT NULL",
                (ev.certificate_id, p.id, p.fingerprint),
            ).fetchone()
            if bound is None:
                raise IllegalTransition(
                    p.state, ev, "no consumed certificate bound to this fingerprint"
                )
            new = p.model_copy(update={"state": target, "nessie_transfer_id": ev.transfer_id})
            cur = conn.execute(
                "UPDATE payment SET state=?, nessie_transfer_id=? "
                "WHERE id=? AND state=? AND fingerprint=?",
                (target.value, ev.transfer_id, p.id, p.state.value, p.fingerprint),
            )
        elif isinstance(ev, Mutated):
            fields = {k: getattr(ev.new, k) for k in PaymentIn.model_fields}
            new = p.model_copy(
                update={
                    **fields,
                    "state": target,
                    "fingerprint": ev.new_fingerprint,
                    "policy_version": ev.policy_version,
                }
            )
            cur = conn.execute(
                "UPDATE payment SET state=?, fingerprint=?, policy_version=?, account_id=?, "
                "amount_cents=?, currency=?, beneficiary_name=?, beneficiary_account_ref=?, "
                "beneficiary_is_new=?, rail=?, conversation_id=? "
                "WHERE id=? AND state=? AND fingerprint=?",
                (
                    target.value,
                    ev.new_fingerprint,
                    ev.policy_version,
                    ev.new.account_id,
                    ev.new.amount_cents,
                    ev.new.currency,
                    ev.new.beneficiary.name,
                    ev.new.beneficiary.account_ref,
                    int(ev.new.beneficiary.is_new),
                    ev.new.rail.value,
                    ev.new.conversation_id,
                    p.id,
                    p.state.value,
                    p.fingerprint,
                ),
            )
        else:
            new = p.model_copy(update={"state": target})
            cur = conn.execute(
                "UPDATE payment SET state=? WHERE id=? AND state=? AND fingerprint=?",
                (target.value, p.id, p.state.value, p.fingerprint),
            )
        if cur.rowcount != 1:
            raise IllegalTransition(p.state, ev, "payment row missing or stale")
        payload: dict[str, object] = {
            "payment_id": p.id,
            "from": p.state.value,
            "to": target.value,
            "from_fingerprint": p.fingerprint,
            "fingerprint": new.fingerprint,
            "event": ev.model_dump(mode="json"),
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
