"""`Kernel.apply` never raises: every refusal or error comes back as a CmdResult.

Includes the cases the first version leaked (amount_cents >= 2**63, Tick with inf or 1e300),
pinned individually in test_found_apply_overflow.py."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from kernel.models import Capability, Rail
from kernel.service import (
    Attest,
    Cmd,
    CmdResult,
    Create,
    IssueCert,
    Mutate,
    Release,
    Tick,
)
from tests.property.driver import Driver
from tests.property.strategies import (
    ACTOR_IDS,
    SymCmd,
    account_contexts,
    conversations,
    ids,
    make_kernel,
    payment_ins,
    traces,
)

MAX_SQLITE_INT = 2**63 - 1

wild_ids = st.one_of(ids(), st.text(max_size=8), st.sampled_from(("pay_nope", "", "cert_0")))
wild_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-5, max_value=MAX_SQLITE_INT),
    st.sampled_from((2**63, 2**64, 10**30)),
    st.floats(allow_nan=True),
    st.text(max_size=6),
    st.lists(st.integers(), max_size=2),
)
wild_patches = st.one_of(
    st.fixed_dictionaries({"amount_cents": wild_values}),
    st.fixed_dictionaries({"rail": st.one_of(st.sampled_from(list(Rail)), wild_values)}),
    st.fixed_dictionaries({"currency": wild_values}),
    st.fixed_dictionaries({"account_id": wild_values}),
    st.fixed_dictionaries({"conversation_id": wild_values}),
    st.fixed_dictionaries(
        {"beneficiary": st.one_of(wild_values, st.dictionaries(st.text(max_size=6), wild_values))}
    ),
    st.dictionaries(st.text(max_size=6), wild_values, max_size=3),
)

wild_cmds: st.SearchStrategy[Cmd] = st.one_of(
    st.builds(Create, payment=payment_ins(), ctx=account_contexts(), conversation=conversations()),
    st.builds(
        Attest,
        payment_id=wild_ids,
        actor_id=st.one_of(st.sampled_from(ACTOR_IDS), wild_ids),
        capability=st.sampled_from(list(Capability)),
        note=st.one_of(st.none(), st.text(max_size=20)),
    ),
    st.builds(
        IssueCert,
        payment_id=wild_ids,
        actor_id=wild_ids,
        capability=st.sampled_from(list(Capability)),
    ),
    st.builds(Release, payment_id=wild_ids, certificate_id=wild_ids, nonce=wild_ids),
    st.builds(Mutate, payment_id=wild_ids, patch=wild_patches, ctx=account_contexts()),
    st.builds(
        Tick,
        seconds=st.one_of(
            st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
            st.sampled_from((float("nan"), float("inf"), -float("inf"), 1e300)),
        ),
    ),
)


def _check(r: object) -> None:
    assert isinstance(r, CmdResult)
    if r.ok:
        assert r.invariant is None and r.error is None
    else:
        assert r.invariant is not None or r.error


@settings(deadline=None)
@given(st.lists(wild_cmds, max_size=12))
def test_apply_never_raises_on_wild_commands(cmds: list[Cmd]) -> None:
    kernel, _ = make_kernel()
    for cmd in cmds:
        _check(kernel.apply(cmd))
    assert kernel.audit_verify().ok


@settings(deadline=None)
@given(traces(), st.lists(wild_cmds, max_size=6))
def test_apply_never_raises_on_traces_with_real_ids(trace: list[SymCmd], extra: list[Cmd]) -> None:
    kernel, clock = make_kernel()
    d = Driver(kernel, clock)
    for s in d.run(trace):
        _check(s.result)
    pids = d.payments or ["pay_nope"]
    for i, cmd in enumerate(extra):
        # Point wild commands at real payments too.
        if isinstance(cmd, Attest | IssueCert | Release | Mutate) and i % 2 == 0:
            cmd = type(cmd)(**{**cmd.__dict__, "payment_id": pids[i % len(pids)]})
        _check(kernel.apply(cmd))
    assert kernel.audit_verify().ok
