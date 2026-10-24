"""Found by the apply-never-raises property, then fixed in the kernel the same night.

Create or Mutate with amount_cents >= 2**63 passes Pydantic (PositiveInt is unbounded) and
sqlite3 raises OverflowError on bind; Tick with inf or an astronomically large number of
seconds raises OverflowError from timedelta. The first version of `Kernel.apply` let these
escape. The kernel refactor added a catch-all that turns them into `CmdResult(ok=False)`.
These pins keep the contract "apply never raises" from regressing.
"""

from __future__ import annotations

from kernel.service import CmdResult, Create, Kernel, Mutate, Tick
from tests.factories import account_context, payment_in
from tests.property.strategies import make_kernel


def _fresh() -> Kernel:
    kernel, _ = make_kernel()
    return kernel


def _refused(r: CmdResult) -> None:
    assert isinstance(r, CmdResult)
    assert not r.ok and r.error


def test_create_with_amount_at_2_pow_63_does_not_raise() -> None:
    kernel = _fresh()
    _refused(kernel.apply(Create(payment=payment_in(amount_cents=2**63), ctx=account_context())))
    assert kernel.audit_verify().ok


def test_mutate_to_amount_at_2_pow_63_does_not_raise() -> None:
    kernel = _fresh()
    created = kernel.apply(Create(payment=payment_in(), ctx=account_context()))
    assert created.ok and created.payment is not None
    r = kernel.apply(
        Mutate(payment_id=created.payment.id, patch={"amount_cents": 2**63}, ctx=account_context())
    )
    _refused(r)
    # The failed mutation left the payment untouched.
    after = kernel.get(created.payment.id).payment
    assert after == created.payment
    assert kernel.audit_verify().ok


def test_tick_infinity_does_not_raise() -> None:
    _refused(_fresh().apply(Tick(seconds=float("inf"))))


def test_tick_huge_does_not_raise() -> None:
    _refused(_fresh().apply(Tick(seconds=1e300)))
