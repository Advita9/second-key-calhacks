"""Decisions, signals and transcripts survive a restart (SQLite tables, same transaction)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from kernel.clock import FakeClock
from kernel.llm.types import EvidenceItem, ExtractorResult, Signal
from kernel.models import Outcome, PaymentIn, State
from kernel.policy.engine import EXTRACTOR_FAIL_RULE_ID, V1_PATH, load_policy
from kernel.service import Kernel
from tests.factories import account_context, payment_in

CONV = (EvidenceItem(id="EV-0003", speaker="caller", text="Do not tell your bank"),)


class _Secrecy:
    """Deterministic 'model': cites EV-0003 when it is in the transcript, else nothing."""

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        self.calls += 1
        if not any(e.id == "EV-0003" for e in conversation):
            return ExtractorResult()
        return ExtractorResult(
            signals=(
                Signal(kind="secrecy", score=0.9, source_id="EV-0003", evidence_span="Do not tell"),
            ),
            summary="secrecy",
        )


def _kernel(db: str, clock: FakeClock, ext: _Secrecy) -> Kernel:
    return Kernel(db, policy=load_policy(V1_PATH), clock=clock, extractor=ext)


def test_decision_and_signals_survive_restart(tmp_path: Path, clock: FakeClock) -> None:
    db = str(tmp_path / "k.db")
    first = _kernel(db, clock, _Secrecy())
    p, d = first.create_payment(payment_in(), account_context(), CONV)
    assert p.state is State.HELD and d.rule_ids == ("H-02", "A-01")
    plain, _ = first.create_payment(payment_in(amount_cents=1), account_context())
    first.conn.close()

    second = _kernel(db, clock, _Secrecy())
    rec = second.get(p.id)
    assert rec.decision == d
    assert len(rec.signals) == 1 and rec.signals[0].source_id == "EV-0003"
    listed = {r.payment.id: r for r in second.list_payments()}
    listed_decision = listed[p.id].decision
    assert listed_decision is not None and listed_decision.rule_ids == d.rule_ids
    assert listed[plain.id].decision is not None and listed[plain.id].signals == ()
    assert second.audit_verify().ok


def test_decision_row_is_written_in_the_decided_transaction(kernel: Kernel) -> None:
    p, d = kernel.create_payment(payment_in(), account_context(), CONV)
    rows = kernel.conn.execute(
        "SELECT outcome, rule_ids, policy_version FROM decision WHERE payment_id=?", (p.id,)
    ).fetchall()
    assert rows == [(d.outcome.value, '["A-01"]', "v1")]
    kernel.mutate(p.id, {"amount_cents": 800_001}, account_context())
    n = kernel.conn.execute("SELECT count(*) FROM decision WHERE payment_id=?", (p.id,)).fetchone()
    assert n == (2,)
    assert kernel.get(p.id).decision is not None


def test_mutate_after_restart_reuses_persisted_transcript(tmp_path: Path, clock: FakeClock) -> None:
    db = str(tmp_path / "k.db")
    first = _kernel(db, clock, _Secrecy())
    p, d = first.create_payment(payment_in(), account_context(), CONV)
    assert p.state is State.HELD
    first.conn.close()

    ext = _Secrecy()
    second = _kernel(db, clock, ext)
    p2, d2 = second.mutate(p.id, {"amount_cents": 800_001}, account_context())
    assert ext.calls == 1  # the extractor ran on the stored transcript
    assert p2.state is State.HELD and d2.rule_ids == ("H-02", "A-01")
    assert EXTRACTOR_FAIL_RULE_ID not in d2.rule_ids
    assert second.get(p.id).signals[0].kind == "secrecy"


def test_empty_transcript_is_still_a_transcript(tmp_path: Path, clock: FakeClock) -> None:
    """Created with no conversation: after a restart mutate must not fail closed, because the
    transcript is present (and empty), not absent."""
    db = str(tmp_path / "k.db")
    first = _kernel(db, clock, _Secrecy())
    p, _ = first.create_payment(payment_in(), account_context())
    first.conn.close()
    second = _kernel(db, clock, _Secrecy())
    p2, d2 = second.mutate(p.id, {"amount_cents": 800_001}, account_context())
    assert d2.outcome is Outcome.ALLOW and EXTRACTOR_FAIL_RULE_ID not in d2.rule_ids
    assert p2.state is State.ELIGIBLE_TO_SUBMIT


def test_memory_kernel_uses_the_tables_too(kernel: Kernel) -> None:
    p, d = kernel.create_payment(payment_in(), account_context(), CONV)
    assert (
        kernel.conn.execute(
            "SELECT evidence FROM conversation WHERE payment_id=?", (p.id,)
        ).fetchone()
        is not None
    )
    rec = kernel.get(p.id)
    assert rec.decision == d
