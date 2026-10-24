"""I3: a certificate is one-time, nonce-bound, expires, and is refused on replay."""

from __future__ import annotations

import threading
from collections import Counter

from hypothesis import event, given, settings
from hypothesis import strategies as st

from kernel.models import Capability, Invariant, Refusal, State
from kernel.service import Release
from tests.property.driver import Driver
from tests.property.strategies import SCreate, SymCmd, eligible_creates, make_kernel, traces


@settings(deadline=None)
@given(traces())
def test_release_matches_the_shadow_oracle_exactly(trace: list[SymCmd]) -> None:
    """Every Release answers exactly what the documented check order predicts from the
    ids, nonces and clock the kernel handed out. Covers replay, expiry, wrong nonce,
    forged ids, other payments' certs, voided certs and denied payments."""
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if not isinstance(s.cmd, Release):
            continue
        expected = d.expected_release(s)
        got = None if s.result.ok else (s.result.invariant or "error")
        event(f"release -> {expected}")
        assert got == expected, (s.cmd, s.result)


@settings(deadline=None)
@given(traces())
def test_no_certificate_releases_twice(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    steps = d.run(trace)
    uses = Counter(
        s.cmd.certificate_id for s in steps if isinstance(s.cmd, Release) and s.result.ok
    )
    assert all(n == 1 for n in uses.values()), uses
    for s in steps:
        if not isinstance(s.cmd, Release) or s.result.ok:
            continue
        info = d.cert_by_id.get(s.cmd.certificate_id)
        if info is None or info.payment_id != s.payment_id:
            continue
        if info.id in s.extra["released_before"]:
            event("replay")
            assert s.result.invariant is Invariant.I3_REPLAY
            assert s.state_after is State.SUBMITTED


@settings(deadline=None)
@given(traces())
def test_expiry_is_enforced_on_the_fake_clock(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        if not isinstance(s.cmd, Release) or s.state_before is State.DENIED:
            continue
        info = d.cert_by_id.get(s.cmd.certificate_id)
        if info is None or info.payment_id != s.payment_id:
            continue
        if info.epoch != s.extra["epoch_before"] or info.id in s.extra["released_before"]:
            continue
        if info.id in s.extra["voided_before"]:
            continue  # voided by a sibling release or cancel: I2 wins, see the oracle test
        if info.expires_at <= s.now:
            event("expired")
            assert not s.result.ok and s.result.invariant is Invariant.I3_EXPIRED
        elif s.cmd.nonce == info.nonce and s.state_before is State.ELIGIBLE_TO_SUBMIT:
            assert s.result.ok and s.state_after is State.SUBMITTED
        elif s.cmd.nonce != info.nonce:
            assert not s.result.ok and s.result.invariant is Invariant.I1_NO_CERT


@settings(deadline=None)
@given(eligible_creates(), st.integers(min_value=2, max_value=4))
def test_threads_racing_one_certificate_give_exactly_one_success(
    create: SCreate, n_threads: int
) -> None:
    kernel, _ = make_kernel()
    payment, decision = kernel.create_payment(create.payment, create.ctx, create.conversation)
    assert payment.state is State.ELIGIBLE_TO_SUBMIT, decision
    cert = kernel.issue_certificate(payment.id, "ops_1", Capability.BANK_REVIEW)
    barrier = threading.Barrier(n_threads)
    results: list[object] = []
    lock = threading.Lock()

    def go() -> None:
        barrier.wait()
        try:
            out: object = kernel.release(payment.id, cert.id, cert.nonce).state
        except Refusal as r:
            out = r.invariant
        with lock:
            results.append(out)

    threads = [threading.Thread(target=go) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(results) == n_threads
    assert results.count(State.SUBMITTED) == 1
    assert results.count(Invariant.I3_REPLAY) == n_threads - 1
    rec = kernel.get(payment.id)
    assert rec.payment.state is State.SUBMITTED
    assert sum(c.consumed_at is not None for c in rec.certificates) == 1
    assert kernel.audit_verify().ok
