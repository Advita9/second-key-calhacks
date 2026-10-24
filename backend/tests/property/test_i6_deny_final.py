"""I6: DENY is not overridable by any actor. HOLD is lifted only by BANK_REVIEW.

A successful Mutate also leaves HELD, but only into PENDING_REVIEW with a fresh policy
decision and every prior attestation voided; that is a new review, not a lift. DENIED is
not mutable at all, which is what makes DENY final."""

from __future__ import annotations

from hypothesis import event, given, settings

from kernel.models import Capability, Invariant, Outcome, State
from kernel.service import Attest, Mutate, Release
from tests.property.driver import Cancel, Driver
from tests.property.strategies import SymCmd, make_kernel, traces


@settings(deadline=None)
@given(traces())
def test_denied_is_terminal_and_every_attempt_refuses_with_i6(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    steps = d.run(trace)
    for s in steps:
        if s.state_before is not State.DENIED:
            continue
        event(f"{type(s.cmd).__name__} on DENIED")
        assert not s.result.ok
        assert s.result.invariant is Invariant.I6_DENIED
        assert s.result.certificate is None
        assert s.payment_after == s.payment_before
    denied = {
        s.payment_id
        for s in steps
        if s.result.decision is not None and s.result.decision.outcome is Outcome.DENY
    }
    for pid in d.payments:
        rec = kernel.get(pid)
        if pid in denied:
            assert rec.payment.state is State.DENIED
        if rec.payment.state is State.DENIED:
            assert all(c.consumed_at is None for c in rec.certificates)
            assert rec.payment.nessie_transfer_id is None


@settings(deadline=None)
@given(traces())
def test_held_leaves_only_via_bank_review_fresh_review_or_cancel(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock, snapshot=True)
    for s in d.run(trace):
        if s.state_before is not State.HELD:
            continue
        if s.state_after is State.HELD:
            continue
        assert s.result.ok
        if isinstance(s.cmd, Attest):
            event("hold lifted by BANK_REVIEW")
            assert s.cmd.capability is Capability.BANK_REVIEW
            assert s.state_after is State.ELIGIBLE_TO_SUBMIT
            assert s.payment_before is not None
            assert s.cmd.actor_id != s.payment_before.beneficiary.account_ref
        elif isinstance(s.cmd, Cancel):
            event("held payment cancelled")
            assert s.state_after is State.CANCELLED
        else:
            event("held payment mutated into a fresh review")
            assert isinstance(s.cmd, Mutate)
            assert s.result.decision is not None
            assert s.record_after is not None
            assert all(a.voided_at is not None for a in s.record_after.attestations)


@settings(deadline=None)
@given(traces())
def test_cancel_is_terminal_and_nothing_on_it_can_release(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock, snapshot=True)
    cancelled: set[str] = set()
    for s in d.run(trace):
        if isinstance(s.cmd, Cancel):
            if s.result.ok:
                event(f"cancelled from {s.state_before}")
                assert s.payment_id is not None
                assert s.state_before not in (State.DENIED, State.SUBMITTED, State.CANCELLED)
                assert s.state_after is State.CANCELLED
                assert s.record_after is not None
                assert all(a.voided_at is not None for a in s.record_after.attestations)
                assert all(c.voided_at is not None for c in s.record_after.certificates)
                cancelled.add(s.payment_id)
            else:
                assert s.payment_after == s.payment_before
                if s.state_before is State.DENIED:
                    assert s.result.invariant is Invariant.I6_DENIED
                elif s.state_before in (State.SUBMITTED, State.CANCELLED):
                    assert s.result.invariant is Invariant.I1_NOT_ELIGIBLE
            continue
        if s.payment_id not in cancelled:
            continue
        assert not s.result.ok
        assert s.state_after is State.CANCELLED
        assert s.result.certificate is None
        if isinstance(s.cmd, Release):
            info = d.cert_by_id.get(s.cmd.certificate_id)
            if info is not None and info.payment_id == s.payment_id:
                assert s.result.invariant is Invariant.I2_FINGERPRINT
            else:
                assert s.result.invariant is Invariant.I1_NO_CERT
        else:
            assert s.result.invariant is Invariant.I1_NOT_ELIGIBLE
    for pid in cancelled:
        rec = kernel.get(pid)
        assert rec.payment.state is State.CANCELLED
        assert all(c.consumed_at is None for c in rec.certificates)


@settings(deadline=None)
@given(traces())
def test_only_bank_review_attest_moves_any_state(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if not isinstance(s.cmd, Attest):
            continue
        if s.cmd.capability is Capability.BANK_REVIEW and s.result.ok:
            assert s.state_after is (
                State.ELIGIBLE_TO_SUBMIT if s.state_before is State.HELD else s.state_before
            )
        else:
            assert s.state_after == s.state_before
