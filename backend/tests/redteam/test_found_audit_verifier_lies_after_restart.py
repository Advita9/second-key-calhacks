"""FOUND (red): `audit_verify()` reports ok=True after the audit tail is erased while the
kernel is down and the kernel is restarted. The verifier lies.

I7 says: "Audit log is hash-chained; GET /audit/verify detects any edit to past records."
In-process it does: `AuditLog` keeps an anchor (seq, hash) of the last row it wrote, so deleting
or editing a row during the process is caught (length < anchor, or chain mismatch). But the
anchor is NOT persisted. On restart `AuditLog.__init__` reads whatever the tail currently is and
adopts it as the anchor. So an attacker with DB access can:

    1. stop the kernel,
    2. DELETE the tail rows (e.g. CERT_CONSUMED, RELEASED) or the whole audit table,
    3. start the kernel,

and `/audit/verify` returns ok=True while the payment row still reads SUBMITTED. The hash chain
alone cannot detect tail truncation; the only guard (the in-process anchor) is lost on restart.
A durable high-water mark (or cross-checking the SpacetimeDB `audit_mirror`) would close this.

This asserts the SECURE behaviour (verify must flag the erased history), so it is RED today.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from kernel.clock import FakeClock
from kernel.models import Capability, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.service import Kernel
from tests.factories import account_context, payment_in


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))


def _release_once(db_path: str) -> str:
    kernel = Kernel(db_path, policy=load_policy(V1_PATH), clock=_clock())
    ctx = account_context(prior_payees=["ext_bay_roofing"], mule_list=[])
    payment, _ = kernel.create_payment(payment_in(amount_cents=10_000), ctx)
    cert = kernel.issue_certificate(payment.id, "ops", Capability.BANK_REVIEW)
    kernel.release(payment.id, cert.id, cert.nonce)
    assert kernel.audit_verify().ok
    assert kernel.get(payment.id).payment.state is State.SUBMITTED
    kernel.conn.close()  # the kernel shuts down
    return payment.id


def test_erasing_the_audit_tail_while_down_is_detected_after_restart(tmp_path: object) -> None:
    db_path = str(tmp_path) + "/kernel.db"  # type: ignore[operator]
    payment_id = _release_once(db_path)

    # Attacker edits the DB directly while the kernel is stopped: drop the last three rows,
    # which include CERT_CONSUMED and RELEASED for the payment that moved money.
    raw = sqlite3.connect(db_path)
    (n,) = raw.execute("SELECT COUNT(*) FROM audit").fetchone()
    raw.execute("DELETE FROM audit WHERE seq > ?", (n - 3,))
    raw.commit()
    raw.close()

    # Kernel restarts and someone calls GET /audit/verify.
    restarted = Kernel(db_path, policy=load_policy(V1_PATH), clock=_clock())
    result = restarted.audit_verify()
    still_submitted = restarted.get(payment_id).payment.state is State.SUBMITTED

    assert still_submitted, "payment row should still show the money moved"
    # SECURE expectation: the chain-verifier must not certify a history whose tail was erased.
    assert not result.ok, (
        "AUDIT VERIFIER LIES: tail rows (incl. RELEASED) erased while down, "
        f"verify() returned ok=True after restart: {result}"
    )


def test_erasing_the_whole_audit_log_is_detected_after_restart(tmp_path: object) -> None:
    db_path = str(tmp_path) + "/kernel2.db"  # type: ignore[operator]
    payment_id = _release_once(db_path)

    raw = sqlite3.connect(db_path)
    raw.execute("DELETE FROM audit")  # erase everything
    raw.commit()
    raw.close()

    restarted = Kernel(db_path, policy=load_policy(V1_PATH), clock=_clock())
    result = restarted.audit_verify()
    assert restarted.get(payment_id).payment.state is State.SUBMITTED
    assert not result.ok, (
        "AUDIT VERIFIER LIES: entire audit log erased while down, verify() ok=True after restart"
    )
