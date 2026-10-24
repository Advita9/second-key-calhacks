"""`Kernel.apply` never raises; refusals come back as ok=False with the invariant."""

from __future__ import annotations

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from kernel.clock import FakeClock
from kernel.models import Beneficiary, Capability, Invariant, PaymentIn, Rail, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.service import (
    Attest,
    Cmd,
    CmdResult,
    Create,
    IssueCert,
    Kernel,
    Mutate,
    Release,
    Tick,
)
from tests.factories import account_context, payment_in

PIDS = ["p0", "p1", "pay_nope"]
ACTORS = ["ops_1", "priya", "ext_bay_roofing", "ext_9f31"]
REFS = ["ext_bay_roofing", "ext_9f31", "ext_new"]


def _payment_in(ref: str, rail: Rail, amount: int) -> PaymentIn:
    return payment_in(
        amount_cents=amount,
        beneficiary=Beneficiary(name="n", account_ref=ref, is_new=ref == "ext_new"),
        rail=rail,
    )


cmd_strategy: st.SearchStrategy[Cmd] = st.one_of(
    st.builds(
        Create,
        payment=st.builds(
            _payment_in,
            st.sampled_from(REFS),
            st.sampled_from(list(Rail)),
            st.sampled_from([100, 800_000, 5_000_000]),
        ),
        ctx=st.just(account_context()),
    ),
    st.builds(
        Attest,
        payment_id=st.sampled_from(PIDS),
        actor_id=st.sampled_from(ACTORS),
        capability=st.sampled_from(list(Capability)),
        note=st.none(),
    ),
    st.builds(
        IssueCert,
        payment_id=st.sampled_from(PIDS),
        actor_id=st.sampled_from(ACTORS),
        capability=st.sampled_from(list(Capability)),
    ),
    st.builds(
        Release,
        payment_id=st.sampled_from(PIDS),
        certificate_id=st.sampled_from(["c0", "cert_nope", ""]),
        nonce=st.sampled_from(["", "00", "deadbeef"]),
    ),
    st.builds(
        Mutate,
        payment_id=st.sampled_from(PIDS),
        patch=st.sampled_from(
            [{"amount_cents": 1}, {"beneficiary": {"account_ref": "ext_9f31"}}, {"bad": 1}, {}]
        ),
        ctx=st.just(account_context()),
    ),
    st.builds(Tick, seconds=st.sampled_from([0.0, 60.0, 121.0])),
)


def _bind(cmd: Cmd, real: dict[str, str]) -> Cmd:
    """Map the symbolic ids p0/p1 (and c0) onto ids the kernel actually minted."""
    if isinstance(cmd, Create | Tick):
        return cmd
    pid = real.get(cmd.payment_id, cmd.payment_id)
    if isinstance(cmd, Release):
        return Release(pid, real.get(cmd.certificate_id, cmd.certificate_id), cmd.nonce)
    return replace(cmd, payment_id=pid)


@settings(max_examples=60, deadline=None)
@given(st.lists(cmd_strategy, max_size=12))
def test_apply_never_raises(cmds: list[Cmd]) -> None:
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=FakeClock())
    real: dict[str, str] = {}
    for i, ref in enumerate(["ext_bay_roofing", "ext_new"]):
        p, _ = kernel.create_payment(_payment_in(ref, Rail.ACH, 800_000), account_context())
        real[f"p{i}"] = p.id
    cert = kernel.issue_certificate(real["p0"], "ops_1", Capability.BANK_REVIEW)
    real["c0"] = cert.id
    for cmd in cmds:
        r = kernel.apply(_bind(cmd, real))
        assert isinstance(r, CmdResult)
        if not r.ok:
            assert r.invariant is not None or r.error
        else:
            assert r.invariant is None and r.error is None
    assert kernel.audit_verify().ok


def test_apply_reports_invariant(kernel: Kernel) -> None:
    r = kernel.apply(Create(payment=payment_in(), ctx=account_context()))
    assert r.ok and r.payment is not None and r.payment.state is State.ELIGIBLE_TO_SUBMIT
    pid = r.payment.id
    bad = kernel.apply(
        IssueCert(payment_id=pid, actor_id="priya", capability=Capability.CO_APPROVER)
    )
    assert not bad.ok and bad.invariant is Invariant.I1_NOT_ELIGIBLE
    good = kernel.apply(
        IssueCert(payment_id=pid, actor_id="ops", capability=Capability.BANK_REVIEW)
    )
    assert good.ok and good.certificate is not None
    cert = good.certificate
    kernel.apply(Tick(seconds=121))
    r = kernel.apply(Release(payment_id=pid, certificate_id=cert.id, nonce=cert.nonce))
    assert not r.ok and r.invariant is Invariant.I3_EXPIRED
    r = kernel.apply(Release(payment_id="pay_nope", certificate_id=cert.id, nonce=cert.nonce))
    assert not r.ok and r.invariant is None and r.error


def test_tick_without_fake_clock_is_an_error() -> None:
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH))
    r = kernel.apply(Tick(seconds=1))
    assert not r.ok and r.error


def test_apply_never_raises_on_ill_typed_cmd(kernel: Kernel) -> None:
    r = kernel.apply(Create(payment=payment_in(), ctx=account_context()))
    assert r.ok and r.payment is not None
    pid = r.payment.id
    cert = kernel.issue_certificate(pid, "ops_1", Capability.BANK_REVIEW)
    bad_cmds: list[object] = [
        Release(payment_id=pid, certificate_id=cert.id, nonce=None),  # type: ignore[arg-type]
        Release(payment_id=pid, certificate_id=None, nonce=cert.nonce),  # type: ignore[arg-type]
        Release(payment_id=None, certificate_id=cert.id, nonce=cert.nonce),  # type: ignore[arg-type]
        Attest(payment_id=pid, actor_id="x", capability="BANK_REVIEW"),  # type: ignore[arg-type]
        Attest(payment_id=pid, actor_id=None, capability=Capability.CO_APPROVER),  # type: ignore[arg-type]
        IssueCert(payment_id=pid, actor_id="x", capability="nope"),  # type: ignore[arg-type]
        Mutate(payment_id=pid, patch=None, ctx=account_context()),  # type: ignore[arg-type]
        Mutate(payment_id=pid, patch={"amount_cents": "lots"}, ctx=account_context()),
        Mutate(payment_id=pid, patch={"amount_cents": 1}, ctx=None),  # type: ignore[arg-type]
        Create(payment={"amount_cents": 1}, ctx=account_context()),  # type: ignore[arg-type]
        Create(payment=payment_in(), ctx=account_context(), conversation=None),  # type: ignore[arg-type]
        Tick(seconds="soon"),  # type: ignore[arg-type]
        "not a command",
    ]
    for cmd in bad_cmds:
        res = kernel.apply(cmd)  # type: ignore[arg-type]
        assert isinstance(res, CmdResult) and not res.ok and res.error, cmd
    # The kernel is still healthy and the real certificate still works.
    assert kernel.audit_verify().ok
    assert kernel.release(pid, cert.id, cert.nonce).state is State.SUBMITTED
