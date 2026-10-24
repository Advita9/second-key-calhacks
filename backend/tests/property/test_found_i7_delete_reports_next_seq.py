"""Found by the I7 property on the first kernel: deleting a middle audit row was detected
(I7 held) but `verify()` named the row after the gap instead of the gap. Fixed in
kernel/audit.py (reports `expected_seq`). Kept as a pin so the location claim cannot regress.
"""

from __future__ import annotations

from kernel.service import Create
from tests.factories import account_context, payment_in
from tests.property.strategies import make_kernel


def test_deleting_a_middle_row_reports_the_gap_seq() -> None:
    kernel, _ = make_kernel()
    assert kernel.apply(Create(payment=payment_in(), ctx=account_context())).ok
    (n,) = kernel.conn.execute("SELECT COUNT(*) FROM audit").fetchone()
    assert n >= 4
    kernel.conn.execute("DELETE FROM audit WHERE seq=2")
    r = kernel.audit_verify()
    assert not r.ok
    assert r.first_bad_seq == 2
