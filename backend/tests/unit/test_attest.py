"""I5 and I6: capabilities, conflicts, terminal states, and fail-closed model/rail paths."""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import cast

import pytest

from kernel.clock import FakeClock
from kernel.llm.types import EvidenceItem, ExtractorResult, Signal
from kernel.models import (
    Beneficiary,
    Capability,
    Certificate,
    Invariant,
    Outcome,
    Payment,
    PaymentIn,
    Rail,
    Refusal,
    State,
)
from kernel.policy.engine import EXTRACTOR_FAIL_RULE_ID, V1_PATH, load_policy
from kernel.rail import RailError
from kernel.service import Kernel
from tests.factories import account_context, payment_in


def held(kernel: Kernel) -> str:
    p, d = kernel.create_payment(
        payment_in(
            beneficiary=Beneficiary(name="Priya Patel", account_ref="ext_priya", is_new=True),
            rail=Rail.ZELLE,
        ),
        account_context(),
    )
    assert p.state is State.HELD and "H-01" in d.rule_ids
    return p.id


def denied(kernel: Kernel) -> str:
    p, _ = kernel.create_payment(
        payment_in(beneficiary=Beneficiary(name="x", account_ref="ext_9f31", is_new=True)),
        account_context(),
    )
    assert p.state is State.DENIED
    return p.id


# I5 ------------------------------------------------------------------------------------


def test_co_approver_who_is_beneficiary_cannot_attest(kernel: Kernel) -> None:
    pid = held(kernel)
    with pytest.raises(Refusal) as ei:
        kernel.attest(pid, "ext_priya", Capability.CO_APPROVER, "I confirm, it is fine")
    assert ei.value.invariant is Invariant.I5_CONFLICT
    rec = kernel.get(pid)
    assert rec.attestations == [] and rec.payment.state is State.HELD
    assert (
        rec.history[-1].kind == "REFUSED" and rec.history[-1].payload["invariant"] == "I5_CONFLICT"
    )


def test_conflict_is_by_ref_not_display_name(kernel: Kernel) -> None:
    pid = held(kernel)
    # Same display name as the beneficiary but a different id: not a conflict.
    p = kernel.attest(pid, "priya_patel_2", Capability.CO_APPROVER)
    assert len(kernel.get(pid).attestations) == 1 and p.state is State.HELD
    # Different display name, same ref as the beneficiary: conflict.
    with pytest.raises(Refusal) as ei:
        kernel.attest(pid, "ext_priya", Capability.CUSTOMER_CHECKIN)
    assert ei.value.invariant is Invariant.I5_CONFLICT


def test_co_approver_on_held_stays_held(kernel: Kernel) -> None:
    pid = held(kernel)
    p = kernel.attest(pid, "daughter_1", Capability.CO_APPROVER, "she asked me")
    assert p.state is State.HELD
    rec = kernel.get(pid)
    assert [a.capability for a in rec.attestations] == [Capability.CO_APPROVER]
    assert rec.attestations[0].fingerprint == p.fingerprint
    assert rec.attestations[0].note == "she asked me"


def test_customer_checkin_cannot_lift_hold(kernel: Kernel) -> None:
    pid = held(kernel)
    p = kernel.attest(pid, "acc_margaret", Capability.CUSTOMER_CHECKIN, "yes I want this")
    assert p.state is State.HELD


def test_co_approver_cannot_issue_certificate(kernel: Kernel) -> None:
    pid = held(kernel)
    kernel.attest(pid, "ops_1", Capability.BANK_REVIEW)
    assert kernel.get(pid).payment.state is State.ELIGIBLE_TO_SUBMIT
    for cap in (Capability.CO_APPROVER, Capability.CUSTOMER_CHECKIN):
        with pytest.raises(Refusal) as ei:
            kernel.issue_certificate(pid, "daughter_1", cap)
        assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
        last = kernel.audit.tail(1)[0]
        assert last.kind == "REFUSED" and last.payload["reason"] == "CERT_REFUSED_CAPABILITY"
    assert kernel.get(pid).certificates == []


def test_bank_review_lifts_hold(kernel: Kernel) -> None:
    pid = held(kernel)
    p = kernel.attest(pid, "ops_1", Capability.BANK_REVIEW, "called customer back")
    assert p.state is State.ELIGIBLE_TO_SUBMIT
    kinds = [e.kind for e in kernel.get(pid).history]
    assert kinds[-2:] == ["ATTESTED", "HOLD_LIFTED"]


def test_bank_review_on_pending_only_adds_row(kernel: Kernel) -> None:
    pid = held(kernel)
    kernel.attest(pid, "ops_1", Capability.BANK_REVIEW)
    p = kernel.attest(pid, "ops_2", Capability.BANK_REVIEW)
    assert p.state is State.ELIGIBLE_TO_SUBMIT and len(kernel.get(pid).attestations) == 2


def test_cert_needs_eligible_state(kernel: Kernel) -> None:
    pid = held(kernel)
    with pytest.raises(Refusal) as ei:
        kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE


# I6 ------------------------------------------------------------------------------------


def test_denied_never_changes(kernel: Kernel) -> None:
    pid = denied(kernel)
    for cap in Capability:
        with pytest.raises(Refusal) as ei:
            kernel.attest(pid, "ops_1", cap)
        assert ei.value.invariant is Invariant.I6_DENIED
    with pytest.raises(Refusal) as ei:
        kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I6_DENIED
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, "cert_x", "nonce")
    assert ei.value.invariant is Invariant.I6_DENIED
    with pytest.raises(Refusal) as ei:
        kernel.mutate(pid, {"amount_cents": 1}, account_context())
    assert ei.value.invariant is Invariant.I6_DENIED
    rec = kernel.get(pid)
    assert rec.payment.state is State.DENIED and rec.attestations == [] and rec.certificates == []
    assert sum(1 for e in rec.history if e.kind == "REFUSED") == 6


def test_submitted_is_terminal(kernel: Kernel) -> None:
    p, _ = kernel.create_payment(payment_in(), account_context())
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    kernel.release(p.id, cert.id, cert.nonce)
    with pytest.raises(Refusal) as ei:
        kernel.attest(p.id, "ops_1", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
    with pytest.raises(Refusal) as ei:
        kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE


# rail failure ----------------------------------------------------------------------------


class FlakyRail:
    def __init__(self) -> None:
        self.calls = 0

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("nessie down")
        return f"tr_{self.calls}"


def test_rail_failure_leaves_payment_and_cert_untouched(clock: FakeClock) -> None:
    rail = FlakyRail()
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, rail=rail)
    p, _ = kernel.create_payment(payment_in(), account_context())
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(RailError):
        kernel.release(p.id, cert.id, cert.nonce)
    rec = kernel.get(p.id)
    assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT
    assert rec.payment.nessie_transfer_id is None
    assert rec.certificates[0].consumed_at is None
    assert rec.history[-1].kind == "RAIL_FAILED"
    assert kernel.audit_verify().ok
    # Nothing was consumed, so the same certificate still works once the rail is back.
    p2 = kernel.release(p.id, cert.id, cert.nonce)
    assert p2.state is State.SUBMITTED and p2.nessie_transfer_id == "tr_2"


# extractor paths (I4) ----------------------------------------------------------------------


class BrokenExtractor:
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        raise RuntimeError("model returned garbage")


class SlowExtractor:
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        time.sleep(0.5)
        return ExtractorResult()


class SecrecyExtractor:
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        return ExtractorResult(
            signals=(
                Signal(kind="secrecy", score=0.9, source_id="EV-0003", evidence_span="Do not tell"),
            ),
            summary="caller demanded secrecy",
        )


class WrongTypeExtractor:
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        return {"signals": [], "summary": "ok"}  # type: ignore[return-value]


def test_extractor_exception_fails_closed_with_x00(clock: FakeClock) -> None:
    kernel = Kernel(
        ":memory:", policy=load_policy(V1_PATH), clock=clock, extractor=BrokenExtractor()
    )
    p, d = kernel.create_payment(payment_in(), account_context())
    assert d.outcome is Outcome.HOLD and p.state is State.HELD
    assert d.rule_ids == ("A-01", EXTRACTOR_FAIL_RULE_ID)
    assert kernel.get(p.id).history[-2].kind == "EXTRACTOR_FAILED"


def test_extractor_timeout_fails_closed_with_x00(clock: FakeClock) -> None:
    kernel = Kernel(
        ":memory:",
        policy=load_policy(V1_PATH),
        clock=clock,
        extractor=SlowExtractor(),
        extractor_timeout_s=0.05,
    )
    p, d = kernel.create_payment(payment_in(), account_context())
    assert p.state is State.HELD and EXTRACTOR_FAIL_RULE_ID in d.rule_ids


def test_extractor_wrong_type_fails_closed(clock: FakeClock) -> None:
    kernel = Kernel(
        ":memory:", policy=load_policy(V1_PATH), clock=clock, extractor=WrongTypeExtractor()
    )
    p, d = kernel.create_payment(payment_in(), account_context())
    assert p.state is State.HELD and EXTRACTOR_FAIL_RULE_ID in d.rule_ids


def test_extractor_failure_on_mutate_also_fails_closed(clock: FakeClock) -> None:
    kernel = Kernel(
        ":memory:", policy=load_policy(V1_PATH), clock=clock, extractor=BrokenExtractor()
    )
    p, _ = kernel.create_payment(payment_in(), account_context())
    p2, d2 = kernel.mutate(p.id, {"amount_cents": 1}, account_context())
    assert p2.state is State.HELD and EXTRACTOR_FAIL_RULE_ID in d2.rule_ids


def test_signals_only_reach_state_through_policy(clock: FakeClock) -> None:
    kernel = Kernel(
        ":memory:", policy=load_policy(V1_PATH), clock=clock, extractor=SecrecyExtractor()
    )
    conv = [EvidenceItem(id="EV-0003", speaker="caller", text="Do not tell your bank")]
    p, d = kernel.create_payment(payment_in(), account_context(), conv)
    assert p.state is State.HELD and d.rule_ids == ("H-02", "A-01")
    rec = kernel.get(p.id)
    assert rec.signals[0].kind == "secrecy" and rec.decision == d
    extracted = [e for e in rec.history if e.kind == "EXTRACTED"][0]
    signals = cast(list[dict[str, object]], extracted.payload["signals"])
    assert signals[0]["source_id"] == "EV-0003"


def test_null_extractor_still_holds_scenario_a(kernel: Kernel) -> None:
    p, d = kernel.create_payment(
        payment_in(
            amount_cents=1_850_000,
            beneficiary=Beneficiary(name="Agent Daniels", account_ref="ext_new", is_new=True),
            rail=Rail.WIRE,
        ),
        account_context(),
    )
    assert p.state is State.HELD and d.rule_ids == ("H-01", "H-03")


def test_unknown_payment_is_key_error(kernel: Kernel) -> None:
    with pytest.raises(KeyError):
        kernel.get("pay_nope")
    with pytest.raises(KeyError):
        kernel.attest("pay_nope", "x", Capability.BANK_REVIEW)
