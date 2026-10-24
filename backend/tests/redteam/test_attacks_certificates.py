"""BLOCKED (green regressions): certificate and release attacks. I1, I2, I3.

create -> attest -> certificate -> mutate 1 cent -> release old cert (I2); release twice (I3);
release with an expired certificate via FakeClock (I3); release with another payment's cert,
a forged id, the right id and wrong nonce (I1); two concurrent releases with the same
certificate from several threads (exactly one SUBMITTED, the rest I3_REPLAY).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest

from kernel.clock import FakeClock
from kernel.models import Capability, Refusal, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.service import Kernel
from tests.factories import account_context, payment_in

ALLOW_CTX = account_context(prior_payees=["ext_bay_roofing"], mule_list=[])


def _kernel() -> Kernel:
    return Kernel(
        ":memory:",
        policy=load_policy(V1_PATH),
        clock=FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC)),
    )


def _eligible(kernel: Kernel, amount: int = 10_000) -> str:
    payment, decision = kernel.create_payment(payment_in(amount_cents=amount), ALLOW_CTX)
    assert decision.outcome.value == "ALLOW" and payment.state is State.ELIGIBLE_TO_SUBMIT
    return payment.id


def test_release_with_another_payments_certificate_is_i1() -> None:
    kernel = _kernel()
    a = _eligible(kernel)
    b = _eligible(kernel)
    cert_a = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as e:
        kernel.release(b, cert_a.id, cert_a.nonce)
    assert e.value.invariant.value == "I1_NO_CERT"
    assert kernel.get(b).payment.state is State.ELIGIBLE_TO_SUBMIT


def test_release_with_forged_certificate_id_is_i1() -> None:
    kernel = _kernel()
    a = _eligible(kernel)
    cert = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as e:
        kernel.release(a, "cert_deadbeefdeadbeef", cert.nonce)
    assert e.value.invariant.value == "I1_NO_CERT"


def test_release_with_wrong_nonce_is_i1() -> None:
    kernel = _kernel()
    a = _eligible(kernel)
    cert = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as e:
        kernel.release(a, cert.id, "0" * 32)
    assert e.value.invariant.value == "I1_NO_CERT"
    assert kernel.get(a).payment.state is State.ELIGIBLE_TO_SUBMIT


def test_mutate_one_cent_voids_cert_then_release_is_i2() -> None:
    kernel = _kernel()
    a = _eligible(kernel, amount=800_000)
    cert = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    kernel.mutate(a, {"amount_cents": 800_001}, ALLOW_CTX)
    with pytest.raises(Refusal) as e:
        kernel.release(a, cert.id, cert.nonce)
    assert e.value.invariant.value == "I2_FINGERPRINT"
    assert kernel.get(a).payment.state is not State.SUBMITTED


def test_release_twice_is_i3_replay() -> None:
    kernel = _kernel()
    a = _eligible(kernel)
    cert = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    assert kernel.release(a, cert.id, cert.nonce).state is State.SUBMITTED
    with pytest.raises(Refusal) as e:
        kernel.release(a, cert.id, cert.nonce)
    assert e.value.invariant.value == "I3_REPLAY"


def test_release_with_expired_certificate_is_i3_expired() -> None:
    clock = FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC))
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, cert_ttl_s=120)
    a = _eligible(kernel)
    cert = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    clock.advance(121)
    with pytest.raises(Refusal) as e:
        kernel.release(a, cert.id, cert.nonce)
    assert e.value.invariant.value == "I3_EXPIRED"
    assert kernel.get(a).payment.state is State.ELIGIBLE_TO_SUBMIT


def test_concurrent_releases_same_cert_submit_exactly_once() -> None:
    kernel = _kernel()
    a = _eligible(kernel)
    cert = kernel.issue_certificate(a, "ops", Capability.BANK_REVIEW)
    results: list[tuple[str, str]] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            state = kernel.release(a, cert.id, cert.nonce).state.value
            with lock:
                results.append(("ok", state))
        except Refusal as r:
            with lock:
                results.append(("refused", r.invariant.value))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    submitted = [r for r in results if r == ("ok", "SUBMITTED")]
    assert len(submitted) == 1, results
    assert all(r == ("refused", "I3_REPLAY") for r in results if r[0] != "ok")
    assert kernel.get(a).payment.state is State.SUBMITTED
    assert kernel.audit_verify().ok
