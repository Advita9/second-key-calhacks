"""I5 and I6: capabilities, conflicts, terminal states, and fail-closed model/rail paths."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from pathlib import Path
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
from kernel.nessie import MOCK_KEY, MockNessieTransport, NessieClient, NessieRail
from kernel.policy.engine import EXTRACTOR_FAIL_RULE_ID, V1_PATH, load_policy
from kernel.rail import RailError, RailUnknownOutcome
from kernel.service import Kernel
from kernel.state import IllegalTransition, Released
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


def test_bank_review_who_is_beneficiary_cannot_lift_hold(kernel: Kernel) -> None:
    pid = held(kernel)  # beneficiary account_ref is ext_priya
    with pytest.raises(Refusal) as ei:
        kernel.attest(pid, "ext_priya", Capability.BANK_REVIEW, "approving my own payment")
    assert ei.value.invariant is Invariant.I5_CONFLICT
    rec = kernel.get(pid)
    assert rec.payment.state is State.HELD and rec.attestations == []
    kernel.attest(pid, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as ei:
        kernel.issue_certificate(pid, "ext_priya", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I5_CONFLICT


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


def test_rail_failure_has_no_cert_consumed_row(clock: FakeClock) -> None:
    rail = FlakyRail()
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, rail=rail)
    p, _ = kernel.create_payment(payment_in(), account_context())
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(RailError):
        kernel.release(p.id, cert.id, cert.nonce)
    row = kernel.conn.execute(
        "SELECT consumed_at, voided_at FROM certificate WHERE id=?", (cert.id,)
    ).fetchone()
    assert row == (None, None)
    assert kernel.conn.execute(
        "SELECT state, nessie_transfer_id FROM payment WHERE id=?", (p.id,)
    ).fetchone() == ("ELIGIBLE_TO_SUBMIT", None)
    assert "CERT_CONSUMED" not in [e.kind for e in kernel.get(p.id).history]


class _RailThatBreaksTheCert:
    """Submits, then voids the certificate row so transition(Released) must refuse (A5)."""

    def __init__(self, kernel_ref: list[Kernel]) -> None:
        self.kernel_ref = kernel_ref

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        self.kernel_ref[0].conn.execute(
            "UPDATE certificate SET voided_at='2026-01-01T00:00:00+00:00' WHERE id=?",
            (certificate.id,),
        )
        return "tr_money_moved"


def test_transition_failure_after_rail_success_is_audited(clock: FakeClock) -> None:
    """B1: if anything fails after the rail returned, the transfer id must be in the audit log,
    verify() must stay green, and no certificate on the payment may release again."""
    ref: list[Kernel] = []
    kernel = Kernel(
        ":memory:", policy=load_policy(V1_PATH), clock=clock, rail=_RailThatBreaksTheCert(ref)
    )
    ref.append(kernel)
    p, _ = kernel.create_payment(payment_in(), account_context())
    c1 = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    c2 = kernel.issue_certificate(p.id, "ops_2", Capability.BANK_REVIEW)
    with pytest.raises(IllegalTransition):
        kernel.release(p.id, c1.id, c1.nonce)
    rec = kernel.get(p.id)
    assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT  # transaction rolled back
    last = rec.history[-1]
    assert last.kind == "RELEASE_UNRECORDED"
    assert (
        last.payload["transfer_id"] == "tr_money_moved" and last.payload["certificate_id"] == c1.id
    )
    assert kernel.audit_verify().ok
    assert all(c.voided_at is not None for c in rec.certificates)
    for c in (c1, c2):
        with pytest.raises(Refusal) as ei:
            kernel.release(p.id, c.id, c.nonce)
        # Frozen (reason RELEASE_UNRECORDED) before the voided cert is even looked at.
        assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE


def test_transition_failure_after_rail_success_via_monkeypatch(
    clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kernel.state import transition as real

    def broken(p: Payment, ev: object, **kw: object) -> Payment:
        if isinstance(ev, Released):
            raise RuntimeError("db hiccup after rail")
        return real(p, ev, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr("kernel.service.transition", broken)
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock)
    p, _ = kernel.create_payment(payment_in(), account_context())
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(RuntimeError):
        kernel.release(p.id, cert.id, cert.nonce)
    rec = kernel.get(p.id)
    assert rec.history[-1].kind == "RELEASE_UNRECORDED"
    assert str(rec.history[-1].payload["transfer_id"]).startswith("mock_tr_")
    assert kernel.audit_verify().ok
    assert rec.certificates[0].voided_at is not None and rec.certificates[0].consumed_at is None


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
    assert p.state is State.HELD and d.rule_ids == ("H-01", "H-03", "H-07")


def test_unknown_payment_is_key_error(kernel: Kernel) -> None:
    with pytest.raises(KeyError):
        kernel.get("pay_nope")
    with pytest.raises(KeyError):
        kernel.attest("pay_nope", "x", Capability.BANK_REVIEW)


class _CountingRail:
    def __init__(self, breaker: list[Kernel]) -> None:
        self.calls = 0
        self.breaker = breaker

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        self.calls += 1
        if self.calls == 1:
            # Simulate the transition failing after money moved (A5 refuses a voided cert).
            self.breaker[0].conn.execute(
                "UPDATE certificate SET voided_at='2026-01-01T00:00:00+00:00' WHERE id=?",
                (certificate.id,),
            )
        return f"tr_{self.calls}"


def test_no_second_release_after_release_unrecorded(clock: FakeClock, tmp_path: Path) -> None:
    """After RELEASE_UNRECORDED the payment is frozen: no fresh cert, no mutate, no release,
    so the rail is never asked to move the money twice. Survives a restart."""
    ref: list[Kernel] = []
    rail = _CountingRail(ref)
    db = str(tmp_path / "k.db")
    kernel = Kernel(db, policy=load_policy(V1_PATH), clock=clock, rail=rail)
    ref.append(kernel)
    p, _ = kernel.create_payment(payment_in(), account_context())
    kernel.attest(p.id, "priya", Capability.CO_APPROVER)
    c1 = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(IllegalTransition):
        kernel.release(p.id, c1.id, c1.nonce)
    assert rail.calls == 1
    assert kernel.get(p.id).history[-1].kind == "RELEASE_UNRECORDED"
    actions: list[Callable[[Kernel], object]] = [
        lambda k: k.issue_certificate(p.id, "ops_2", Capability.BANK_REVIEW),
        lambda k: k.mutate(p.id, {"amount_cents": 1}, account_context()),
        lambda k: k.release(p.id, c1.id, c1.nonce),
    ]
    for action in actions:
        with pytest.raises(Refusal) as ei:
            action(kernel)
        assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
        assert kernel.audit.tail(1)[0].payload["reason"] == "RELEASE_UNRECORDED"
    # BANK_REVIEW can still look at it and cancel it; that is the operator's reconciliation path.
    kernel.attest(p.id, "ops_1", Capability.BANK_REVIEW, "reconciling with the rail")
    kernel.conn.close()
    restarted = Kernel(db, policy=load_policy(V1_PATH), clock=clock, rail=rail)
    with pytest.raises(Refusal) as ei:
        restarted.issue_certificate(p.id, "ops_3", Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I1_NOT_ELIGIBLE
    assert rail.calls == 1
    assert restarted.audit_verify().ok


def _nessie_kernel(clock: FakeClock, transport: MockNessieTransport) -> Kernel:
    rail = NessieRail(
        NessieClient(key=MOCK_KEY, transport=transport),
        payee_accounts={"acc_margaret": "acc_margaret"},
    )
    return Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, rail=rail)


def test_rail_partial_failure_voids_certs(clock: FakeClock) -> None:
    """Withdrawal succeeds, deposit fails: unknown outcome. Audit RAIL_PARTIAL with the
    withdrawal id, void every certificate, refuse later ones."""
    t = MockNessieTransport()
    kernel = _nessie_kernel(clock, t)
    p, _ = kernel.create_payment(payment_in(), account_context())
    c1 = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    c2 = kernel.issue_certificate(p.id, "ops_2", Capability.BANK_REVIEW)
    t.fail_with, t.fail_after_writes = 500, 1  # withdrawal passes, deposit fails
    with pytest.raises(RailUnknownOutcome) as ei:
        kernel.release(p.id, c1.id, c1.nonce)
    withdrawal_ids = [row["_id"] for row in t.ledger if row["kind"] == "withdrawal"]
    assert len(withdrawal_ids) == 1 and ei.value.partial_ref == withdrawal_ids[0]
    assert not [row for row in t.ledger if row["kind"] == "deposit"]
    rec = kernel.get(p.id)
    assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT and rec.payment.nessie_transfer_id is None
    last = rec.history[-1]
    assert last.kind == "RAIL_PARTIAL" and last.payload["withdrawal_id"] == withdrawal_ids[0]
    assert all(c.voided_at is not None and c.consumed_at is None for c in rec.certificates)
    for cert in (c1, c2):
        with pytest.raises(Refusal):
            kernel.release(p.id, cert.id, cert.nonce)
    with pytest.raises(Refusal) as ri:
        kernel.issue_certificate(p.id, "ops_3", Capability.BANK_REVIEW)
    assert ri.value.invariant is Invariant.I1_NOT_ELIGIBLE
    assert len([row for row in t.ledger if row["kind"] == "withdrawal"]) == 1
    assert kernel.audit_verify().ok


def test_rail_plain_failure_on_withdrawal_is_not_partial(clock: FakeClock) -> None:
    t = MockNessieTransport()
    kernel = _nessie_kernel(clock, t)
    p, _ = kernel.create_payment(payment_in(), account_context())
    c1 = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    t.fail_with = 500  # the withdrawal itself fails: nothing moved
    with pytest.raises(RailError) as ei:
        kernel.release(p.id, c1.id, c1.nonce)
    assert not isinstance(ei.value, RailUnknownOutcome)
    assert kernel.get(p.id).history[-1].kind == "RAIL_FAILED"
    assert kernel.release(p.id, c1.id, c1.nonce).state is State.SUBMITTED  # cert still live


class _WeirdRail:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls = 0

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        self.calls += 1
        return self.value  # type: ignore[return-value]


@pytest.mark.parametrize("value", [None, "", 123, b"tr_1", ["tr_1"]])
def test_rail_returns_non_string_is_audited(clock: FakeClock, value: object) -> None:
    rail = _WeirdRail(value)
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, rail=rail)
    p, _ = kernel.create_payment(payment_in(), account_context())
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(RailUnknownOutcome):
        kernel.release(p.id, cert.id, cert.nonce)
    rec = kernel.get(p.id)
    assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT
    assert (
        rec.history[-1].kind == "RAIL_PARTIAL" and rec.history[-1].payload["withdrawal_id"] is None
    )
    assert rec.certificates[0].voided_at is not None
    with pytest.raises(Refusal):
        kernel.issue_certificate(p.id, "ops_2", Capability.BANK_REVIEW)
    assert rail.calls == 1 and kernel.audit_verify().ok


def test_actor_label_is_capped() -> None:
    from kernel.service import MAX_ACTOR_LEN, _actor

    assert len(_actor(Capability.BANK_REVIEW, "x" * 500)) == MAX_ACTOR_LEN
    assert _actor(Capability.CO_APPROVER, "priya") == "CO_APPROVER:priya"


@pytest.mark.parametrize("actor_id", ["ext_priya ", " ext_priya", "ext_priya\u200b", "EXT_PRIYA"])
def test_lookalike_actor_ids_are_the_beneficiary_everywhere(kernel: Kernel, actor_id: str) -> None:
    pid = held(kernel)  # beneficiary account_ref ext_priya
    for cap in Capability:
        with pytest.raises(Refusal) as ei:
            kernel.attest(pid, actor_id, cap)
        assert ei.value.invariant is Invariant.I5_CONFLICT
    with pytest.raises(Refusal) as ei:
        kernel.cancel(pid, actor_id, Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I5_CONFLICT
    kernel.attest(pid, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as ei:
        kernel.issue_certificate(pid, actor_id, Capability.BANK_REVIEW)
    assert ei.value.invariant is Invariant.I5_CONFLICT
    assert kernel.get(pid).certificates == []


def test_actor_ids_are_stored_normalized(kernel: Kernel) -> None:
    pid = held(kernel)
    kernel.attest(pid, " OPS_1\u200b", Capability.BANK_REVIEW)
    rec = kernel.get(pid)
    assert rec.attestations[0].actor_id == "ops_1"
    assert rec.history[-2].actor == "BANK_REVIEW:ops_1"
    cert = kernel.issue_certificate(pid, "Ops_2 ", Capability.BANK_REVIEW)
    assert cert.actor_id == "ops_2"
