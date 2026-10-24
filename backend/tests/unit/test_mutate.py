"""I2: any mutation changes the fingerprint and voids every attestation and certificate."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from kernel.clock import FakeClock
from kernel.fingerprint import fingerprint
from kernel.llm.types import EvidenceItem, ExtractorResult
from kernel.models import (
    Beneficiary,
    Capability,
    Invariant,
    Outcome,
    PaymentIn,
    Rail,
    Refusal,
    State,
)
from kernel.policy.engine import V1_PATH, load_policy
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


def test_mutate_then_fresh_cert_releases(kernel: Kernel) -> None:
    pid, old_cid, old_nonce = certified(kernel)
    p, d = kernel.mutate(pid, {"amount_cents": 800_001}, account_context())
    assert p.state is State.ELIGIBLE_TO_SUBMIT
    fresh = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    old = next(c for c in kernel.get(pid).certificates if c.id == old_cid)
    assert fresh.fingerprint == p.fingerprint != old.fingerprint
    with pytest.raises(Refusal):
        kernel.release(pid, old_cid, old_nonce)
    released = kernel.release(pid, fresh.id, fresh.nonce)
    assert released.state is State.SUBMITTED and released.amount_cents == 800_001
    assert kernel.audit_verify().ok


def test_mutate_restamps_policy_version(kernel: Kernel) -> None:
    from pathlib import Path

    from kernel.policy.engine import load_policy

    pid, _, _ = certified(kernel)
    assert kernel.get(pid).payment.policy_version == "v1"
    kernel.policy = load_policy(Path(__file__).parent / "policy_fixtures" / "allow_only.yaml")
    p, d = kernel.mutate(pid, {"amount_cents": 10_000_001}, account_context())
    assert p.policy_version == "allowonly" and d.policy_version == "allowonly"
    assert kernel.get(pid).payment.policy_version == "allowonly"
    assert p.fingerprint == fingerprint(payment_in(amount_cents=10_000_001), "allowonly")
    assert d.outcome is Outcome.ALLOW


class _ActDuringExtraction:
    """An extractor that touches the kernel while mutate has released its lock."""

    def __init__(self) -> None:
        self.kernel: Kernel | None = None
        self.payment_id = ""
        self.action: Callable[[Kernel, str], object] | None = None
        self.armed = False

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        if self.armed and self.kernel is not None and self.action is not None:
            self.armed = False
            self.action(self.kernel, self.payment_id)
        return ExtractorResult()


def _kernel_with(clock: FakeClock, ext: _ActDuringExtraction) -> Kernel:
    k = Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, extractor=ext)
    ext.kernel = k
    return k


def test_mutate_refuses_when_payment_changed_during_extraction(clock: FakeClock) -> None:
    ext = _ActDuringExtraction()
    kernel = _kernel_with(clock, ext)
    p, _ = kernel.create_payment(
        payment_in(
            beneficiary=Beneficiary(name="New", account_ref="ext_new", is_new=True), rail=Rail.WIRE
        ),
        account_context(),
    )
    assert p.state is State.HELD
    ext.payment_id = p.id
    ext.action = lambda k, pid: k.attest(pid, "ops_1", Capability.BANK_REVIEW)  # lifts the hold
    ext.armed = True
    with pytest.raises(Refusal) as ei:
        kernel.mutate(p.id, {"amount_cents": 5}, account_context())
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
    rec = kernel.get(p.id)
    assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT and rec.payment.amount_cents == 800_000
    assert (
        rec.history[-1].kind == "REFUSED" and rec.history[-1].payload["reason"] == "STATE_CHANGED"
    )
    assert kernel.audit_verify().ok


def test_mutate_reports_i6_when_denied_during_extraction(clock: FakeClock) -> None:
    ext = _ActDuringExtraction()
    kernel = _kernel_with(clock, ext)
    p, _ = kernel.create_payment(payment_in(), account_context())
    ext.payment_id = p.id
    ext.action = lambda k, pid: k.mutate(
        pid, {"beneficiary": {"account_ref": "ext_9f31"}}, account_context()
    )
    ext.armed = True
    with pytest.raises(Refusal) as ei:
        kernel.mutate(p.id, {"amount_cents": 5}, account_context())
    assert ei.value.invariant is Invariant.I6_DENIED
    assert kernel.get(p.id).payment.state is State.DENIED


def test_mutate_after_restart_fails_closed(clock: FakeClock, tmp_path: Path) -> None:
    """A new process has no transcript for an old payment; re-deciding must count the
    extractor as failed (X-00) so a HELD-on-signals payment cannot become ALLOW."""
    db = str(tmp_path / "k.db")
    first = Kernel(db, policy=load_policy(V1_PATH), clock=clock, extractor=_SecrecyOnce())
    conv = [EvidenceItem(id="EV-0003", speaker="caller", text="Do not tell your bank")]
    p, d = first.create_payment(payment_in(), account_context(), conv)
    assert p.state is State.HELD and d.rule_ids == ("H-02", "A-01")
    first.conn.close()
    second = Kernel(db, policy=load_policy(V1_PATH), clock=clock)  # NullExtractor, no memory
    p2, d2 = second.mutate(p.id, {"amount_cents": 800_001}, account_context())
    assert p2.state is State.HELD
    assert d2.outcome is Outcome.HOLD and d2.rule_ids == ("A-01", "X-00")
    assert second.get(p.id).history[-2].kind == "EXTRACTOR_FAILED"
    assert second.audit_verify().ok


class _SecrecyOnce:
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        from kernel.llm.types import Signal

        return ExtractorResult(
            signals=(
                Signal(kind="secrecy", score=0.9, source_id="EV-0003", evidence_span="Do not tell"),
            ),
            summary="secrecy",
        )
