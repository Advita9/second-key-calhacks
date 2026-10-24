"""Release certificates (I1, I2, I3): issue, verify, consume once, void on mutation."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timedelta

from kernel.clock import Clock
from kernel.db import immediate
from kernel.models import Capability, Certificate, Invariant, Payment, State

NONCE_BYTES = 16
REDACTED_NONCE = "<redacted>"

_COLS = (
    "id, payment_id, fingerprint, policy_version, actor_id, capability, nonce, "
    "issued_at, expires_at, consumed_at, voided_at"
)


def _row(r: tuple[object, ...]) -> Certificate:
    return Certificate(
        id=str(r[0]),
        payment_id=str(r[1]),
        fingerprint=str(r[2]),
        policy_version=str(r[3]),
        actor_id=str(r[4]),
        capability=Capability(str(r[5])),
        nonce=str(r[6]),
        issued_at=datetime.fromisoformat(str(r[7])),
        expires_at=datetime.fromisoformat(str(r[8])),
        consumed_at=datetime.fromisoformat(str(r[9])) if r[9] is not None else None,
        voided_at=datetime.fromisoformat(str(r[10])) if r[10] is not None else None,
    )


def issue(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    payment: Payment,
    actor_id: str,
    capability: Capability,
    ttl_s: int,
) -> Certificate:
    """Insert a fresh certificate bound to the payment's current fingerprint and policy."""
    now = clock.now()
    cert = Certificate(
        id=f"cert_{secrets.token_hex(8)}",
        payment_id=payment.id,
        fingerprint=payment.fingerprint,
        policy_version=payment.policy_version,
        actor_id=actor_id,
        capability=capability,
        nonce=secrets.token_hex(NONCE_BYTES),
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl_s),
        consumed_at=None,
        voided_at=None,
    )
    with immediate(conn):
        conn.execute(
            f"INSERT INTO certificate ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                cert.id,
                cert.payment_id,
                cert.fingerprint,
                cert.policy_version,
                cert.actor_id,
                cert.capability.value,
                cert.nonce,
                cert.issued_at.isoformat(),
                cert.expires_at.isoformat(),
                None,
                None,
            ),
        )
    return cert


def get(conn: sqlite3.Connection, certificate_id: str) -> Certificate | None:
    r = conn.execute(f"SELECT {_COLS} FROM certificate WHERE id=?", (certificate_id,)).fetchone()
    return _row(r) if r is not None else None


def list_for_payment(conn: sqlite3.Connection, payment_id: str) -> list[Certificate]:
    rows = conn.execute(
        f"SELECT {_COLS} FROM certificate WHERE payment_id=? ORDER BY issued_at, id", (payment_id,)
    ).fetchall()
    return [_row(r) for r in rows]


def verify(cert: Certificate, payment: Payment, nonce: str, now: datetime) -> Invariant | None:
    """Pure. First failing invariant in the fixed order, or None when release may proceed.

    Order: wrong payment -> I1_NO_CERT; voided or fingerprint mismatch -> I2_FINGERPRINT;
    consumed -> I3_REPLAY; expired -> I3_EXPIRED; nonce mismatch -> I1_NO_CERT;
    payment not ELIGIBLE_TO_SUBMIT -> I1_NOT_ELIGIBLE. (DENIED is checked by the caller first.)
    """
    if cert.payment_id != payment.id:
        return Invariant.I1_NO_CERT
    if cert.voided_at is not None or cert.fingerprint != payment.fingerprint:
        return Invariant.I2_FINGERPRINT
    if cert.policy_version != payment.policy_version:
        return Invariant.I2_FINGERPRINT
    if cert.consumed_at is not None:
        return Invariant.I3_REPLAY
    if cert.expires_at <= now:
        return Invariant.I3_EXPIRED
    if not secrets.compare_digest(cert.nonce.encode(), nonce.encode()):
        return Invariant.I1_NO_CERT
    if payment.state is not State.ELIGIBLE_TO_SUBMIT:
        return Invariant.I1_NOT_ELIGIBLE
    return None


def consume(conn: sqlite3.Connection, certificate_id: str, fingerprint: str, now: datetime) -> bool:
    """Atomically mark the certificate consumed. True iff exactly one row changed.

    Must run inside the caller's BEGIN IMMEDIATE so a concurrent release cannot interleave.
    """
    cur = conn.execute(
        "UPDATE certificate SET consumed_at=? WHERE id=? AND consumed_at IS NULL "
        "AND voided_at IS NULL AND fingerprint=?",
        (now.isoformat(), certificate_id, fingerprint),
    )
    return cur.rowcount == 1


def void_all_for_payment(conn: sqlite3.Connection, payment_id: str, now: datetime) -> int:
    cur = conn.execute(
        "UPDATE certificate SET voided_at=? WHERE payment_id=? AND voided_at IS NULL",
        (now.isoformat(), payment_id),
    )
    return int(cur.rowcount)


def redact(cert: Certificate) -> Certificate:
    """Copy without the bearer secret, for records that leave the kernel."""
    return cert.model_copy(update={"nonce": REDACTED_NONCE})
