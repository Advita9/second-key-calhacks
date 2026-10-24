"""Found by the I7 property: deleting a middle audit row is detected (I7 holds) but
`verify()` reports `first_bad_seq` as the seq of the row *after* the gap, not the gap.

With rows 1..4 and row 2 deleted, verify returns ok=False, first_bad_seq=3. The gap is at 2.
`AuditLog.verify` returns the row's own seq when `seq != expected_seq`; returning
`expected_seq` would name the missing row. Reporting only; detection is not affected.
Non-strict on purpose: it flips to XPASS without failing the suite once kernel/audit.py
reports the gap; drop the mark then.
"""

from __future__ import annotations

import pytest

from kernel.service import Create
from tests.factories import account_context, payment_in
from tests.property.strategies import make_kernel


@pytest.mark.xfail(strict=False, reason="I7: verify names the row after a deleted middle row")
def test_deleting_a_middle_row_reports_the_gap_seq() -> None:
    kernel, _ = make_kernel()
    assert kernel.apply(Create(payment=payment_in(), ctx=account_context())).ok
    (n,) = kernel.conn.execute("SELECT COUNT(*) FROM audit").fetchone()
    assert n >= 4
    kernel.conn.execute("DELETE FROM audit WHERE seq=2")
    r = kernel.audit_verify()
    assert not r.ok
    assert r.first_bad_seq == 2
