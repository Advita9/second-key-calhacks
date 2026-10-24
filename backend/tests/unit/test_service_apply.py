"""`Kernel.apply` never raises; refusals come back as ok=False with the invariant."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from kernel.clock import FakeClock
from kernel.models import Beneficiary, Capability, Invariant, Rail, State
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


def _payment_in(ref: str, rail: Rail, amount: int) -> object:
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


@settings(max_examples=60, deadline=None)
@given(st.lists(cmd_strategy, max_size=12))
def test_apply_never_raises(cmds: list[Cmd]) -> None:
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH), clock=FakeClock())
    for cmd in cmds:
        r = kernel.apply(cmd)
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
