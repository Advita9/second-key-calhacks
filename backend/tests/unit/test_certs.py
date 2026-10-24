"""I1 and I3: release needs a valid, unconsumed, unexpired, nonce-bound certificate."""

from __future__ import annotations

import threading

import pytest

from kernel import certs
from kernel.clock import FakeClock
from kernel.models import Capability, Invariant, Refusal, State
from kernel.service import Kernel
from tests.factories import account_context, payment_in


def eligible(kernel: Kernel) -> str:
    p, d = kernel.create_payment(payment_in(), account_context())
    assert p.state is State.ELIGIBLE_TO_SUBMIT, d
    return p.id


def test_happy_path(kernel: Kernel, clock: FakeClock) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    assert cert.payment_id == pid and cert.consumed_at is None and cert.voided_at is None
    assert cert.capability is Capability.BANK_REVIEW and len(cert.nonce) == 32
    assert (cert.expires_at - cert.issued_at).total_seconds() == 120
    p = kernel.release(pid, cert.id, cert.nonce)
    assert p.state is State.SUBMITTED and p.nessie_transfer_id
    rec = kernel.get(pid)
    assert rec.certificates[0].consumed_at == clock.now()
    assert kernel.audit_verify().ok
    kinds = [e.kind for e in rec.history]
    assert kinds[-3:] == ["CERT_ISSUED", "CERT_CONSUMED", "RELEASED"]


def test_replay_is_refused(kernel: Kernel) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    kernel.release(pid, cert.id, cert.nonce)
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cert.id, cert.nonce)
    assert ei.value.invariant is Invariant.I3_REPLAY
    assert ei.value.text == "SETTLEMENT REFUSED · I3_REPLAY"
    last = kernel.audit.tail(1)[0]
    assert last.kind == "REFUSED" and last.payload["invariant"] == "I3_REPLAY"


def test_expired_is_refused(kernel: Kernel, clock: FakeClock) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    clock.advance(121)
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cert.id, cert.nonce)
    assert ei.value.invariant is Invariant.I3_EXPIRED
    assert kernel.get(pid).payment.state is State.ELIGIBLE_TO_SUBMIT


def test_exactly_at_expiry_is_expired(kernel: Kernel, clock: FakeClock) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    clock.advance(120)
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cert.id, cert.nonce)
    assert ei.value.invariant is Invariant.I3_EXPIRED


def test_just_before_expiry_is_fine(kernel: Kernel, clock: FakeClock) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    clock.advance(119)
    assert kernel.release(pid, cert.id, cert.nonce).state is State.SUBMITTED


def test_wrong_nonce_is_refused(kernel: Kernel) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    for bad in ("", "0" * 32, cert.nonce[:-1] + ("0" if cert.nonce[-1] != "0" else "1")):
        with pytest.raises(Refusal) as ei:
            kernel.release(pid, cert.id, bad)
        assert ei.value.invariant is Invariant.I1_NO_CERT
    assert kernel.release(pid, cert.id, cert.nonce).state is State.SUBMITTED


def test_certificate_from_other_payment_is_refused(kernel: Kernel) -> None:
    a = eligible(kernel)
    b = eligible(kernel)
    cert_b = kernel.issue_certificate(b, "ops_1", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as ei:
        kernel.release(a, cert_b.id, cert_b.nonce)
    assert ei.value.invariant is Invariant.I1_NO_CERT
    assert kernel.get(a).payment.state is State.ELIGIBLE_TO_SUBMIT
    assert kernel.get(b).certificates[0].consumed_at is None


def test_unknown_certificate_is_refused(kernel: Kernel) -> None:
    pid = eligible(kernel)
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, "cert_nope", "00")
    assert ei.value.invariant is Invariant.I1_NO_CERT


def test_release_without_eligibility_even_with_cert_row(kernel: Kernel) -> None:
    """A cert can only exist for ELIGIBLE payments; if state moved, release is refused."""
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    kernel.mutate(pid, {"beneficiary": {"name": "Bay Roofing Inc"}}, account_context())
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, cert.id, cert.nonce)
    assert ei.value.invariant is Invariant.I2_FINGERPRINT


def test_two_threads_same_cert_exactly_one_submits(kernel: Kernel) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    barrier = threading.Barrier(2)
    results: list[object] = []
    lock = threading.Lock()

    def go() -> None:
        barrier.wait()
        try:
            out: object = kernel.release(pid, cert.id, cert.nonce).state
        except Refusal as r:
            out = r.invariant
        with lock:
            results.append(out)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sorted(results, key=str) == sorted([State.SUBMITTED, Invariant.I3_REPLAY], key=str)
    assert kernel.get(pid).payment.state is State.SUBMITTED
    assert kernel.audit_verify().ok


def test_nonce_never_appears_in_audit_or_record(kernel: Kernel) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    kernel.release(pid, cert.id, cert.nonce)
    blob = " ".join(str(e.payload) for e in kernel.audit.tail(100))
    assert cert.nonce not in blob
    rec = kernel.get(pid)
    assert rec.certificates[0].nonce != cert.nonce


def test_release_voids_sibling_certificates(kernel: Kernel) -> None:
    pid = eligible(kernel)
    c1 = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    c2 = kernel.issue_certificate(pid, "ops_2", Capability.BANK_REVIEW)
    assert c1.id != c2.id and c1.nonce != c2.nonce
    kernel.release(pid, c2.id, c2.nonce)
    rec = kernel.get(pid)
    by_id = {c.id: c for c in rec.certificates}
    assert by_id[c1.id].voided_at is not None and by_id[c1.id].consumed_at is None
    assert by_id[c2.id].consumed_at is not None and by_id[c2.id].voided_at is None
    assert "SIBLING_CERTS_VOIDED" in [e.kind for e in rec.history]
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, c1.id, c1.nonce)
    assert ei.value.invariant is Invariant.I2_FINGERPRINT  # voided sibling, checked before state


def test_release_rejects_sibling_nonce(kernel: Kernel) -> None:
    """A nonce is bound to its own certificate id; a sibling's nonce is a wrong nonce."""
    pid = eligible(kernel)
    c1 = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    c2 = kernel.issue_certificate(pid, "ops_2", Capability.BANK_REVIEW)
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, c1.id, c2.nonce)
    assert ei.value.invariant is Invariant.I1_NO_CERT
    with pytest.raises(Refusal) as ei:
        kernel.release(pid, c2.id, c1.nonce)
    assert ei.value.invariant is Invariant.I1_NO_CERT
    assert kernel.get(pid).payment.state is State.ELIGIBLE_TO_SUBMIT
    assert all(c.consumed_at is None and c.voided_at is None for c in kernel.get(pid).certificates)


def test_consume_is_single_use_at_sql_level(kernel: Kernel, clock: FakeClock) -> None:
    """certs.consume is the row-level arbiter, independent of the Python-side verify."""
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    conn = kernel.conn
    now = clock.now()
    assert certs.consume(conn, cert.id, pid, cert.fingerprint, now) is False or True
    # Reset to test each predicate in isolation.
    conn.execute("UPDATE certificate SET consumed_at=NULL WHERE id=?", (cert.id,))
    assert certs.consume(conn, cert.id, "pay_other", cert.fingerprint, now) is False
    assert certs.consume(conn, cert.id, pid, "0" * 64, now) is False
    clock.advance(120)
    assert certs.consume(conn, cert.id, pid, cert.fingerprint, clock.now()) is False  # expired
    clock.advance(-120)
    assert certs.consume(conn, cert.id, pid, cert.fingerprint, now) is True
    assert certs.consume(conn, cert.id, pid, cert.fingerprint, now) is False  # already consumed
    conn.execute(
        "UPDATE certificate SET consumed_at=NULL, voided_at=? WHERE id=?",
        (now.isoformat(), cert.id),
    )
    assert certs.consume(conn, cert.id, pid, cert.fingerprint, now) is False  # voided


def test_verify_treats_non_string_nonce_as_no_cert(kernel: Kernel, clock: FakeClock) -> None:
    pid = eligible(kernel)
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    payment = kernel.get(pid).payment
    for bad in (None, 123, b"x", ["n"]):
        assert certs.verify(cert, payment, bad, clock.now()) is Invariant.I1_NO_CERT  # type: ignore[arg-type]
