"""I2: any mutation changes the fingerprint and voids every attestation and certificate."""

from __future__ import annotations

import pytest

from kernel.models import Beneficiary, Capability, Invariant, Outcome, Rail, Refusal, State
from kernel.service import Kernel
from tests.factories import account_context, payment_in


def certified(kernel: Kernel) -> tuple[str, str, str]:
    p, _ = kernel.create_payment(payment_in(), account_context())
    assert p.state is State.ELIGIBLE_TO_SUBMIT
    kernel.attest(p.id, "priya", Capability.CO_APPROVER, "looks right")
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    return p.id, cert.id, cert.nonce


def test_amount_by_one_cent_voids_everything(kernel: Kernel) -> None:
    pid, cid, nonce = certified(kernel)
    before = kernel.get(pid)
    p, d = kernel.mutate(pid, {"amount_cents": 800_001}, account_context())
    assert p.fingerprint != before.payment.fingerprint
    assert p.amount_cents == 800_001
    rec = kernel.get(pid)
    assert all(a.voided_at is not None for a in rec.attestations) and rec.attestations
    assert all(c.voided_at is not None for c in rec.certificates) and rec.certificates
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cid, nonce)
    assert ei.value.invariant is Invariant.I2_FINGERPRINT
    assert kernel.get(pid).payment.state is not State.SUBMITTED
    assert kernel.audit_verify().ok


def test_mutate_re_runs_policy(kernel: Kernel) -> None:
    pid, _, _ = certified(kernel)
    p, d = kernel.mutate(pid, {"amount_cents": 800_001}, account_context())
    assert d.outcome is Outcome.ALLOW and p.state is State.ELIGIBLE_TO_SUBMIT
    p, d = kernel.mutate(pid, {"beneficiary": {"account_ref": "ext_9f31"}}, account_context())
    assert d.outcome is Outcome.DENY and p.state is State.DENIED and "D-01" in d.rule_ids


def test_name_only_mutation_still_voids(kernel: Kernel) -> None:
    """Lead's call: ANY mutate re-runs policy and voids, even when the fingerprint is unchanged
    (the fingerprint covers account_ref, not the display name)."""
    pid, cid, nonce = certified(kernel)
    before = kernel.get(pid).payment
    p, _ = kernel.mutate(pid, {"beneficiary": {"name": "Bay R00fing"}}, account_context())
    assert p.fingerprint == before.fingerprint
    assert p.beneficiary.name == "Bay R00fing"
    rec = kernel.get(pid)
    assert all(a.voided_at is not None for a in rec.attestations)
    assert all(c.voided_at is not None for c in rec.certificates)
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cid, nonce)
    assert ei.value.invariant is Invariant.I2_FINGERPRINT
    kinds = [e.kind for e in rec.history]
    assert "MUTATED" in kinds and kinds.count("DECIDED") == 2


@pytest.mark.parametrize("field", ["account_id", "currency", "rail"])
def test_each_fingerprint_field_changes_it(kernel: Kernel, field: str) -> None:
    pid, _, _ = certified(kernel)
    before = kernel.get(pid).payment.fingerprint
    patch = {"account_id": "acc_other", "currency": "EUR", "rail": "WIRE"}[field]
    p, _ = kernel.mutate(pid, {field: patch}, account_context())
    assert p.fingerprint != before


def test_mutate_submitted_is_refused(kernel: Kernel) -> None:
    pid, cid, nonce = certified(kernel)
    kernel.release(pid, cid, nonce)
    with pytest.raises(Refusal) as ei:
        kernel.mutate(pid, {"amount_cents": 1}, account_context())
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
    assert kernel.get(pid).payment.amount_cents == 800_000


def test_mutate_denied_is_refused(kernel: Kernel) -> None:
    p, _ = kernel.create_payment(
        payment_in(beneficiary=Beneficiary(name="x", account_ref="ext_9f31", is_new=True)),
        account_context(),
    )
    assert p.state is State.DENIED
    with pytest.raises(Refusal) as ei:
        kernel.mutate(p.id, {"beneficiary": {"account_ref": "ext_bay_roofing"}}, account_context())
    assert ei.value.invariant is Invariant.I6_DENIED
    assert kernel.get(p.id).payment.state is State.DENIED


def test_bad_patch_is_rejected_without_change(kernel: Kernel) -> None:
    pid, _, _ = certified(kernel)
    before = kernel.get(pid)
    with pytest.raises(ValueError):
        kernel.mutate(pid, {"amount_cents": -5}, account_context())
    with pytest.raises(ValueError):
        kernel.mutate(pid, {"nope": 1}, account_context())
    with pytest.raises(ValueError):
        kernel.mutate(pid, {"id": "pay_other"}, account_context())
    after = kernel.get(pid)
    assert after.payment == before.payment
    assert all(c.voided_at is None for c in after.certificates)


def test_mutate_from_held_voids_and_redecides(kernel: Kernel) -> None:
    p, d = kernel.create_payment(
        payment_in(
            beneficiary=Beneficiary(name="New Co", account_ref="ext_new", is_new=True),
            rail=Rail.WIRE,
        ),
        account_context(),
    )
    assert p.state is State.HELD
    kernel.attest(p.id, "priya", Capability.CO_APPROVER)
    p2, d2 = kernel.mutate(
        p.id,
        {"beneficiary": {"account_ref": "ext_bay_roofing", "is_new": False}},
        account_context(),
    )
    assert p2.state is State.ELIGIBLE_TO_SUBMIT and d2.outcome is Outcome.ALLOW
    assert all(a.voided_at is not None for a in kernel.get(p.id).attestations)
