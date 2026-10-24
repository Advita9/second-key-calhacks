"""Shared-connection safety: reads under concurrent writes, and a release/mutate race."""

from __future__ import annotations

import random
import threading

from kernel import attest, certs
from kernel.db import load_payment
from kernel.models import Capability, Invariant, Refusal, State
from kernel.service import Kernel
from tests.factories import account_context, payment_in


def test_reads_are_safe_under_concurrent_writes(kernel: Kernel) -> None:
    """Low-level readers take only conn.lock (not the kernel lock) while writers churn."""
    seed_ids = [kernel.create_payment(payment_in(), account_context())[0].id for _ in range(3)]
    stop = threading.Event()
    errors: list[BaseException] = []
    reads = [0]

    def writer(i: int) -> None:
        rng = random.Random(i)
        try:
            for _ in range(40):
                p, _ = kernel.create_payment(payment_in(), account_context())
                kernel.attest(p.id, f"priya{i}", Capability.CO_APPROVER)
                cert = kernel.issue_certificate(p.id, f"ops{i}", Capability.BANK_REVIEW)
                if rng.random() < 0.5:
                    kernel.mutate(p.id, {"amount_cents": 800_001}, account_context())
                else:
                    kernel.release(p.id, cert.id, cert.nonce)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def reader(i: int) -> None:
        rng = random.Random(100 + i)
        try:
            while not stop.is_set():
                pid = rng.choice(seed_ids)
                p = load_payment(kernel.conn, pid)
                assert p.id == pid
                certs.list_for_payment(kernel.conn, pid)
                attest.list_for_payment(kernel.conn, pid)
                kernel.audit.tail(20)
                kernel.audit.for_payment(pid)
                kernel.list_payments(5)
                reads[0] += 1
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    writers = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    readers = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
    for t in readers + writers:
        t.start()
    for t in writers:
        t.join(60)
    stop.set()
    for t in readers:
        t.join(10)
    assert errors == []
    assert reads[0] > 0
    assert kernel.audit_verify().ok
    assert len(kernel.list_payments(500)) == 3 + 4 * 40


def test_release_vs_mutate_race(kernel: Kernel) -> None:
    """Two threads on a barrier: one releases, one mutates. Exactly one wins and the end
    state is consistent either way."""
    p, _ = kernel.create_payment(payment_in(), account_context())
    cert = kernel.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    barrier = threading.Barrier(2)
    outcome: dict[str, object] = {}

    def do_release() -> None:
        barrier.wait()
        try:
            outcome["release"] = kernel.release(p.id, cert.id, cert.nonce).state
        except Refusal as r:
            outcome["release"] = r.invariant

    def do_mutate() -> None:
        barrier.wait()
        try:
            outcome["mutate"] = kernel.mutate(p.id, {"amount_cents": 800_001}, account_context())[
                0
            ].state
        except Refusal as r:
            outcome["mutate"] = r.invariant

    threads = [threading.Thread(target=do_release), threading.Thread(target=do_mutate)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    rec = kernel.get(p.id)
    if outcome["release"] is State.SUBMITTED:
        assert outcome["mutate"] is Invariant.I1_NOT_ELIGIBLE
        assert rec.payment.state is State.SUBMITTED and rec.payment.amount_cents == 800_000
        assert rec.certificates[0].consumed_at is not None
    else:
        assert outcome["mutate"] is State.ELIGIBLE_TO_SUBMIT
        assert outcome["release"] is Invariant.I2_FINGERPRINT
        assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT and rec.payment.amount_cents == 800_001
        assert rec.certificates[0].voided_at is not None and rec.certificates[0].consumed_at is None
    assert kernel.audit_verify().ok
