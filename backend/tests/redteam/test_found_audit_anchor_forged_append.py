"""FOUND (open, final pass, tested at 48d821a): the sidecar anchor is a lower bound only. Rows
APPENDED to the audit table while the kernel is down, with correct chain hashes, are not
detected: `verify()` answers ok=True, anchor="ok", and the sidecar is silently advanced over
the forged rows at the next commit.

`AuditLog._check_anchor` compares the table to `<db>.head.json` like this:

    if len(rows) < seq: mismatch          # shorter tail: caught
    row = rows[seq - 1]
    if row.hash != h: mismatch            # rewritten tail: caught
    return None                           # LONGER tail: accepted as is

and `__init__` then adopts the table's real tail as `_head`. So an attacker with disk access
while the kernel is stopped does not need to touch the sidecar at all (the documented
residual needs both files replaced consistently): computing `chain_hash` for one extra row is
enough to plant, say, a RELEASED or AUDIT_ANCHOR_ACKNOWLEDGED or VOIDED row that the chain,
the anchor and `/audit/verify` all vouch for. By the brief's own criterion ("verify says ok
AND length differs from what the sidecar said") this is a failure: verify ok, table 12 rows,
sidecar 11.

Why the check is loose: a crash between COMMIT and the sidecar write legitimately leaves the
table a few rows ahead (one transaction appends up to four rows). The fix must keep that
window fail-closed instead of silent: when the table is AHEAD of the sidecar at startup report
anchor "ahead" (not "ok"), refuse `append` until `POST /audit/acknowledge`, and have the
acknowledgement record the adopted rows. Alternatively write the sidecar inside the
transaction before COMMIT so the table can never be ahead of it.

These tests assert the SECURE behaviour, so they are RED today.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kernel.audit import AuditChainError, chain_hash
from kernel.clock import FakeClock
from kernel.fingerprint import canonical_json
from kernel.models import Capability, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.service import Kernel
from tests.factories import account_context, payment_in

POLICY = load_policy(V1_PATH)


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))


def _seed(db_path: str) -> tuple[str, int]:
    """One released payment and one open one; returns (open payment id, audit length)."""
    kernel = Kernel(db_path, policy=POLICY, clock=_clock())
    ctx = account_context(prior_payees=["ext_bay_roofing"], mule_list=[])
    paid, _ = kernel.create_payment(payment_in(amount_cents=10_000), ctx)
    cert = kernel.issue_certificate(paid.id, "ops", Capability.BANK_REVIEW)
    kernel.release(paid.id, cert.id, cert.nonce)
    open_payment, _ = kernel.create_payment(payment_in(amount_cents=20_000), ctx)
    assert kernel.get(open_payment.id).payment.state is State.ELIGIBLE_TO_SUBMIT
    length = kernel.audit_verify().length
    kernel.conn.close()
    return open_payment.id, length


def _append_forged_release(db_path: str, payment_id: str) -> int:
    """Attacker with disk access while the kernel is down: one extra, correctly chained row."""
    raw = sqlite3.connect(db_path)
    seq, prev = raw.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    ts = "2026-10-25T09:00:00+00:00"
    payload = canonical_json(
        {
            "payment_id": payment_id,
            "from": "ELIGIBLE_TO_SUBMIT",
            "to": "SUBMITTED",
            "event": {"certificate_id": "cert_forged", "transfer_id": "tx_forged"},
        }
    )
    forged_seq = int(seq) + 1
    h = chain_hash(forged_seq, ts, "release:cert_forged", "RELEASED", payload, str(prev))
    raw.execute(
        "INSERT INTO audit (seq, ts, actor, kind, payload, prev_hash, hash) VALUES (?,?,?,?,?,?,?)",
        (forged_seq, ts, "release:cert_forged", "RELEASED", payload, prev, h),
    )
    raw.commit()
    raw.close()
    return forged_seq


def test_forged_row_appended_while_down_is_detected_at_restart(tmp_path: Path) -> None:
    db_path = str(tmp_path / "kernel.db")
    payment_id, sidecar_len = _seed(db_path)
    forged_seq = _append_forged_release(db_path, payment_id)
    assert json.loads(Path(db_path + ".head.json").read_text("utf-8"))["seq"] == sidecar_len

    restarted = Kernel(db_path, policy=POLICY, clock=_clock())
    result = restarted.audit_verify()
    restarted.conn.close()

    assert result.length == forged_seq == sidecar_len + 1
    # SECURE expectation: a table that is longer than the sidecar says is not "ok".
    assert not (result.ok and result.anchor == "ok"), (
        "AUDIT VERIFIER VOUCHES FOR A FORGED ROW: table has "
        f"{result.length} rows, sidecar anchored {sidecar_len}, verify={result}"
    )


def test_forged_row_appended_while_down_blocks_appends_until_acknowledged(
    tmp_path: Path,
) -> None:
    db_path = str(tmp_path / "kernel2.db")
    payment_id, sidecar_len = _seed(db_path)
    _append_forged_release(db_path, payment_id)

    restarted = Kernel(db_path, policy=POLICY, clock=_clock())
    ctx = account_context(prior_payees=["ext_bay_roofing"], mule_list=[])
    # SECURE expectation: like the shorter-tail case, nothing may be written on top of a tail
    # this process never produced until an operator acknowledges it (audited).
    with pytest.raises(AuditChainError):
        restarted.create_payment(payment_in(amount_cents=10_000), ctx)
    # And the sidecar must not quietly move past the forged row.
    side = json.loads(Path(db_path + ".head.json").read_text("utf-8"))
    restarted.conn.close()
    assert side["seq"] == sidecar_len, f"sidecar advanced over the forged row: {side}"
