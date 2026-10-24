"""Attestations and capability rules (I5). Pure checks plus the attestation table."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime

from kernel.clock import Clock
from kernel.db import immediate
from kernel.models import Attestation, Capability, Invariant, Payment

# Who may do what. CO_APPROVER and CUSTOMER_CHECKIN can only add evidence.
CAN_LIFT_HOLD: frozenset[Capability] = frozenset({Capability.BANK_REVIEW})
CAN_ISSUE_CERT: frozenset[Capability] = frozenset({Capability.BANK_REVIEW})

_COLS = "id, payment_id, actor_id, capability, fingerprint, note, created_at, voided_at"


def conflict(payment: Payment, actor_id: str) -> Invariant | None:
    """I5: an actor whose id is the beneficiary's account_ref may not attest to the payment.

    Compares refs only. Display names are attacker controlled and never consulted.
    """
    if actor_id == payment.beneficiary.account_ref:
        return Invariant.I5_CONFLICT
    return None


def _row(r: tuple[object, ...]) -> Attestation:
    return Attestation(
        id=str(r[0]),
        payment_id=str(r[1]),
        actor_id=str(r[2]),
        capability=Capability(str(r[3])),
        fingerprint=str(r[4]),
        note=str(r[5]) if r[5] is not None else None,
        created_at=datetime.fromisoformat(str(r[6])),
        voided_at=datetime.fromisoformat(str(r[7])) if r[7] is not None else None,
    )


def insert(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    payment: Payment,
    actor_id: str,
    capability: Capability,
    note: str | None,
) -> Attestation:
    att = Attestation(
        id=f"att_{secrets.token_hex(8)}",
        payment_id=payment.id,
        actor_id=actor_id,
        capability=capability,
        fingerprint=payment.fingerprint,
        note=note,
        created_at=clock.now(),
        voided_at=None,
    )
    with immediate(conn):
        conn.execute(
            f"INSERT INTO attestation ({_COLS}) VALUES (?,?,?,?,?,?,?,?)",
            (
                att.id,
                att.payment_id,
                att.actor_id,
                att.capability.value,
                att.fingerprint,
                att.note,
                att.created_at.isoformat(),
                None,
            ),
        )
    return att


def list_for_payment(conn: sqlite3.Connection, payment_id: str) -> list[Attestation]:
    rows = conn.execute(
        f"SELECT {_COLS} FROM attestation WHERE payment_id=? ORDER BY created_at, id",
        (payment_id,),
    ).fetchall()
    return [_row(r) for r in rows]


def void_all_for_payment(conn: sqlite3.Connection, payment_id: str, now: datetime) -> int:
    cur = conn.execute(
        "UPDATE attestation SET voided_at=? WHERE payment_id=? AND voided_at IS NULL",
        (now.isoformat(), payment_id),
    )
    return int(cur.rowcount)
