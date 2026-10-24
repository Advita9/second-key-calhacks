"""Operator cancel: BANK_REVIEW only, I5 conflict applies, CANCELLED is terminal."""

from __future__ import annotations

import pytest

from kernel.models import Beneficiary, Capability, Invariant, Rail, Refusal, State
from kernel.service import Cancel, Kernel
from tests.factories import account_context, payment_in


def _held(kernel: Kernel) -> str:
    p, _ = kernel.create_payment(
        payment_in(
            beneficiary=Beneficiary(name="New", account_ref="ext_new", is_new=True), rail=Rail.WIRE
        ),
        account_context(),
    )
    assert p.state is State.HELD
    return p.id


def _eligible_with_cert(kernel: Kernel) -> tuple[str, str, str]:
    p, _ = kernel.create_payment(payment_in(), account_context())
    kernel.attest(p.id, "priya", Capability.CO_APPROVER)
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    return p.id, cert.id, cert.nonce


def _assert_terminal(kernel: Kernel, pid: str, cert_id: str, nonce: str) -> None:
    for action in (
        lambda: kernel.attest(pid, "ops_1", Capability.BANK_REVIEW),
        lambda: kernel.attest(pid, "priya", Capability.CO_APPROVER),
        lambda: kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW),
        lambda: kernel.mutate(pid, {"amount_cents": 1}, account_context()),
        lambda: kernel.cancel(pid, "ops_1", Capability.BANK_REVIEW),
    ):
        with pytest.raises(Refusal) as ei:
            action()
        assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cert_id, nonce)
    # voided cert -> I2; unknown cert id -> I1_NO_CERT; either way never SUBMITTED
    assert ei.value.invariant in (Invariant.I2_FINGERPRINT, Invariant.I1_NO_CERT)
    assert kernel.get(pid).payment.state is State.CANCELLED


def test_cancel_pre_settlement_voids_and_is_terminal(kernel: Kernel) -> None:
    # ELIGIBLE with an attestation and a live certificate
    pid, cid, nonce = _eligible_with_cert(kernel)
    p = kernel.cancel(pid, "ops_1", Capability.BANK_REVIEW, "looks wrong")
    assert p.state is State.CANCELLED
    rec = kernel.get(pid)
    assert rec.attestations and all(a.voided_at is not None for a in rec.attestations)
    assert rec.certificates and all(c.voided_at is not None for c in rec.certificates)
    kinds = [e.kind for e in rec.history]
    assert kinds[-2:] == ["VOIDED", "CANCELLED"]
    assert rec.history[-1].actor == "BANK_REVIEW:ops_1"
    _assert_terminal(kernel, pid, cid, nonce)
    # HELD with a CO_APPROVER attestation
    hid = _held(kernel)
    kernel.attest(hid, "priya", Capability.CO_APPROVER)
    assert kernel.cancel(hid, "ops_1", Capability.BANK_REVIEW).state is State.CANCELLED
    assert all(a.voided_at is not None for a in kernel.get(hid).attestations)
    _assert_terminal(kernel, hid, "cert_none", "")
    assert kernel.audit_verify().ok


def test_cancel_requires_bank_review(kernel: Kernel) -> None:
    pid = _held(kernel)
    for cap in (Capability.CO_APPROVER, Capability.CUSTOMER_CHECKIN):
        with pytest.raises(Refusal) as ei:
            kernel.cancel(pid, "priya", cap)
        assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
        assert kernel.audit.tail(1)[0].payload["reason"] == "CANCEL_REFUSED_CAPABILITY"
    assert kernel.get(pid).payment.state is State.HELD


def test_cancel_by_beneficiary_is_i5(kernel: Kernel) -> None:
    pid = _held(kernel)  # beneficiary ref ext_new
    with pytest.raises(Refusal) as ei:
        kernel.cancel(pid, "ext_new", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I5_CONFLICT
    assert kernel.get(pid).payment.state is State.HELD


def test_cancel_denied_is_i6_and_submitted_is_not_eligible(kernel: Kernel) -> None:
    p, _ = kernel.create_payment(
        payment_in(beneficiary=Beneficiary(name="x", account_ref="ext_9f31", is_new=True)),
        account_context(),
    )
    assert p.state is State.DENIED
    with pytest.raises(Refusal) as ei:
        kernel.cancel(p.id, "ops_1", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I6_DENIED
    pid, cid, nonce = _eligible_with_cert(kernel)
    kernel.release(pid, cid, nonce)
    with pytest.raises(Refusal) as ei:
        kernel.cancel(pid, "ops_1", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
    assert kernel.get(pid).payment.state is State.SUBMITTED


def test_cancel_via_apply(kernel: Kernel) -> None:
    pid = _held(kernel)
    r = kernel.apply(Cancel(payment_id=pid, actor_id="ops_1", capability=Capability.BANK_REVIEW))
    assert r.ok and r.payment is not None and r.payment.state is State.CANCELLED
    r = kernel.apply(Cancel(payment_id=pid, actor_id="ops_1", capability=Capability.BANK_REVIEW))
    assert not r.ok and r.invariant is Invariant.I1_NOT_ELIGIBLE
    r = kernel.apply(Cancel(payment_id="pay_nope", actor_id="o", capability=Capability.BANK_REVIEW))
    assert not r.ok and r.error
