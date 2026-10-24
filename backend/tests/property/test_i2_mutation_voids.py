"""I2: a mutation of the money-moving fields changes the fingerprint and voids every
attestation and certificate on the payment. Pre-mutation certificates never release."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hypothesis import event, given, settings

from kernel.fingerprint import fingerprint
from kernel.models import Invariant, Payment, PaymentIn, State
from kernel.service import Mutate, Release
from tests.property.driver import Driver
from tests.property.strategies import POLICY, SymCmd, make_kernel, traces


def money_fields(p: Payment) -> tuple[object, ...]:
    return (p.account_id, p.amount_cents, p.currency, p.beneficiary.account_ref, p.rail)


def _patch_landed(after: Payment, patch: Mapping[str, Any]) -> None:
    for k, v in patch.items():
        if k == "beneficiary":
            for kk, vv in v.items():
                assert getattr(after.beneficiary, kk) == vv
        else:
            assert getattr(after, k) == v


@settings(deadline=None)
@given(traces())
def test_mutation_voids_everything_and_fingerprint_tracks_money_fields(
    trace: list[SymCmd],
) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock, snapshot=True)
    for s in d.run(trace):
        if not isinstance(s.cmd, Mutate):
            continue
        if not s.result.ok:
            assert s.payment_after == s.payment_before
            continue
        event("mutated")
        before, after, rec = s.payment_before, s.payment_after, s.record_after
        assert before is not None and after is not None and rec is not None
        assert all(a.voided_at is not None for a in rec.attestations)
        assert all(c.voided_at is not None for c in rec.certificates)
        changed = money_fields(before) != money_fields(after)
        assert (before.fingerprint != after.fingerprint) == changed
        p_in = PaymentIn.model_validate(after.model_dump(include=set(PaymentIn.model_fields)))
        assert after.fingerprint == fingerprint(p_in, POLICY.version)
        assert after.state in (State.HELD, State.ELIGIBLE_TO_SUBMIT, State.DENIED)
        _patch_landed(after, s.cmd.patch)


@settings(deadline=None)
@given(traces())
def test_pre_mutation_certificate_never_releases(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if not isinstance(s.cmd, Release):
            continue
        info = d.cert_by_id.get(s.cmd.certificate_id)
        if info is None or info.payment_id != s.payment_id:
            continue
        if info.epoch == s.extra["epoch_before"]:
            continue
        event("release with pre-mutation certificate")
        assert not s.result.ok
        assert s.state_after == s.state_before
        if s.state_before is State.DENIED:
            assert s.result.invariant is Invariant.I6_DENIED
        else:
            assert s.result.invariant is Invariant.I2_FINGERPRINT


@settings(deadline=None)
@given(traces())
def test_attestations_and_certs_bind_to_the_fingerprint_they_were_made_for(
    trace: list[SymCmd],
) -> None:
    """Every live (unvoided) attestation or certificate carries the payment's current
    fingerprint; anything made for an older fingerprint is voided."""
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    d.run(trace)
    for pid in d.payments:
        rec = kernel.get(pid)
        for a in rec.attestations:
            if a.voided_at is None:
                assert a.fingerprint == rec.payment.fingerprint
        for c in rec.certificates:
            if c.voided_at is None:
                assert c.fingerprint == rec.payment.fingerprint
            else:
                assert c.consumed_at is None  # a consumed cert belongs to a SUBMITTED payment
