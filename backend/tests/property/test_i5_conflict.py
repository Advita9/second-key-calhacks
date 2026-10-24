"""I5: the beneficiary cannot attest or obtain a certificate, whatever capability or display
name they present. CO_APPROVER (and CUSTOMER_CHECKIN) can add evidence only: they never move
a payment out of HELD and never produce a certificate."""

from __future__ import annotations

from hypothesis import event, given, settings

from kernel.models import Capability, Invariant, State
from kernel.service import Attest, IssueCert
from tests.property.driver import TERMINAL, Driver
from tests.property.strategies import SymCmd, make_kernel, traces


@settings(deadline=None)
@given(traces())
def test_beneficiary_as_actor_is_always_refused(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if not isinstance(s.cmd, Attest | IssueCert) or s.payment_before is None:
            continue
        if s.cmd.actor_id != s.payment_before.beneficiary.account_ref:
            continue
        event(f"beneficiary {type(s.cmd).__name__} in {s.state_before}")
        assert not s.result.ok
        assert s.result.certificate is None
        assert s.payment_after == s.payment_before
        inv = s.result.invariant
        if isinstance(s.cmd, Attest):
            if s.state_before in TERMINAL:
                assert inv in (Invariant.I6_DENIED, Invariant.I1_NOT_ELIGIBLE)
            else:
                assert inv is Invariant.I5_CONFLICT
        else:
            # issue_certificate checks state and capability before the conflict, so a
            # beneficiary holding the wrong capability is refused with I1 instead; either
            # way nothing is issued.
            if s.state_before is State.ELIGIBLE_TO_SUBMIT and s.cmd.capability is (
                Capability.BANK_REVIEW
            ):
                assert inv is Invariant.I5_CONFLICT
            else:
                assert inv in (
                    Invariant.I5_CONFLICT,
                    Invariant.I6_DENIED,
                    Invariant.I1_NOT_ELIGIBLE,
                )


@settings(deadline=None)
@given(traces())
def test_no_attestation_or_certificate_row_is_ever_by_the_beneficiary(
    trace: list[SymCmd],
) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if isinstance(s.cmd, Attest | IssueCert) and s.result.ok:
            assert s.payment_before is not None
            assert s.cmd.actor_id != s.payment_before.beneficiary.account_ref
    for info in d.certs:
        rec = kernel.get(info.payment_id)
        for c in rec.certificates:
            # The beneficiary ref at issue time is bound by the fingerprint; an unvoided
            # cert still matches the current beneficiary, so the check is direct.
            if c.voided_at is None:
                assert c.actor_id != rec.payment.beneficiary.account_ref


@settings(deadline=None)
@given(traces())
def test_co_approver_and_checkin_never_change_state_or_issue(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if isinstance(s.cmd, Attest) and s.cmd.capability is not Capability.BANK_REVIEW:
            assert s.state_after == s.state_before
            if s.result.ok:
                event(f"{s.cmd.capability.value} attested in {s.state_before}")
                assert s.state_before not in TERMINAL
        if isinstance(s.cmd, IssueCert) and s.cmd.capability is not Capability.BANK_REVIEW:
            assert not s.result.ok
            assert s.result.certificate is None
            assert s.state_after == s.state_before
            assert (
                s.result.invariant
                in (
                    Invariant.I1_NOT_ELIGIBLE,
                    Invariant.I6_DENIED,
                    Invariant.I5_CONFLICT,
                )
                or s.result.error
            )  # unknown payment id
