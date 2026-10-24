"""I1: no payment reaches SUBMITTED without a valid, unconsumed certificate bound to its
current fingerprint, and only a successful Release with the real nonce gets it there."""

from __future__ import annotations

from hypothesis import event, given, settings

from kernel.models import Invariant, State
from kernel.service import Release
from tests.property.driver import Driver
from tests.property.strategies import SymCmd, make_kernel, traces


@settings(deadline=None)
@given(traces())
def test_submitted_has_exactly_one_consumed_cert_on_current_fingerprint(
    trace: list[SymCmd],
) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    d.run(trace)
    for pid in d.payments:
        rec = kernel.get(pid)
        consumed = [c for c in rec.certificates if c.consumed_at is not None]
        if rec.payment.state is State.SUBMITTED:
            event("reached SUBMITTED")
            assert len(consumed) == 1
            cert = consumed[0]
            assert cert.voided_at is None
            assert cert.fingerprint == rec.payment.fingerprint
            assert cert.policy_version == rec.payment.policy_version
            info = d.cert_by_id[cert.id]
            assert info.payment_id == pid
            assert info.state_at_issue is State.ELIGIBLE_TO_SUBMIT
            # The Release that consumed it presented the real nonce.
            assert d.released.get(cert.id) == info.nonce
            assert rec.payment.nessie_transfer_id
        else:
            assert consumed == []
            assert rec.payment.nessie_transfer_id is None
    assert kernel.audit_verify().ok


@settings(deadline=None)
@given(traces())
def test_only_a_successful_release_with_the_real_nonce_enters_submitted(
    trace: list[SymCmd],
) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        entered = s.state_after is State.SUBMITTED and s.state_before is not State.SUBMITTED
        if entered:
            assert isinstance(s.cmd, Release) and s.result.ok
            assert s.state_before is State.ELIGIBLE_TO_SUBMIT
            info = d.cert_by_id[s.cmd.certificate_id]
            assert info.payment_id == s.payment_id
            assert s.cmd.nonce == info.nonce
        if isinstance(s.cmd, Release):
            # A successful release always submits; a refused one never moves the payment.
            assert s.result.ok == entered
            if not s.result.ok:
                assert s.state_after == s.state_before
        if s.state_before is State.SUBMITTED:
            # Terminal: nothing after settlement succeeds or changes the row.
            assert not s.result.ok
            assert s.state_after is State.SUBMITTED
            assert s.payment_after == s.payment_before
            assert s.result.invariant in (
                Invariant.I1_NOT_ELIGIBLE,
                Invariant.I1_NO_CERT,
                Invariant.I3_REPLAY,
                Invariant.I2_FINGERPRINT,
            )


@settings(deadline=None)
@given(traces())
def test_certificates_are_only_issued_in_eligible_state_by_bank_review(
    trace: list[SymCmd],
) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    d.run(trace)
    for info in d.certs:
        assert info.state_at_issue is State.ELIGIBLE_TO_SUBMIT
    for pid in d.payments:
        for cert in kernel.get(pid).certificates:
            assert cert.capability.value == "BANK_REVIEW"
            assert cert.id in d.cert_by_id
