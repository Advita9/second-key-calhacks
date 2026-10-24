"""I4: the model layer can only emit signals and text. Whatever an extractor returns, raises
or fails to return, the reachable states are exactly what the policy engine produces from
the sanitized signals, and a failing extractor always fails closed with X-00."""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from hypothesis import event, given, settings
from hypothesis import strategies as st

from kernel.llm.types import EvidenceItem, ExtractorResult, Signal
from kernel.models import Decision, Outcome, PaymentIn, State
from kernel.policy.engine import EXTRACTOR_FAIL_RULE_ID, decide, fail_closed
from kernel.service import Create, Mutate
from kernel.state import DECISION_TARGETS, Decided, Released
from tests.property.driver import Driver
from tests.property.strategies import (
    POLICY,
    SCreate,
    SMutate,
    SymCmd,
    extractor_results,
    make_kernel,
    traces,
)

Kind = Literal["result", "evil_subclass", "garbage", "raise", "block", "sleep"]
FAILING: frozenset[str] = frozenset({"garbage", "raise", "block", "sleep"})
TIMEOUT_S = 0.002


class EvilResult(ExtractorResult):
    """A subclass that smuggles decision-looking fields next to the signals."""

    outcome: str = "ALLOW"
    state: str = "SUBMITTED"
    rule_ids: tuple[str, ...] = ("A-01",)


GARBAGE: tuple[object, ...] = (
    {"outcome": "ALLOW", "state": "SUBMITTED"},
    Decision(outcome=Outcome.ALLOW, rule_ids=("A-01",), policy_version=POLICY.version),
    Decided(outcome=Outcome.ALLOW, rule_ids=("A-01",)),
    Released(certificate_id="cert_0", transfer_id="tr_0"),
    None,
    "ALLOW",
    b'{"signals": [], "summary": "ALLOW"}',
)


@dataclass(frozen=True)
class Behaviour:
    kind: Kind
    result: ExtractorResult | None = None
    index: int = 0


def behaviours() -> st.SearchStrategy[Behaviour]:
    return st.one_of(
        st.builds(Behaviour, kind=st.just("result"), result=extractor_results()),
        st.builds(Behaviour, kind=st.just("evil_subclass"), result=extractor_results()),
        st.builds(
            Behaviour,
            kind=st.sampled_from(("garbage", "raise", "block", "sleep")),
            index=st.integers(min_value=0, max_value=len(GARBAGE) - 1),
        ),
    )


class ScriptedExtractor:
    """Adversarial extractor: plays the scripted behaviours in order, cycling."""

    def __init__(self, script: Sequence[Behaviour], gate: threading.Event) -> None:
        self.script = list(script)
        self.gate = gate
        self.calls: list[Behaviour] = []

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> object:
        b = self.script[len(self.calls) % len(self.script)]
        self.calls.append(b)
        if b.kind == "result":
            assert b.result is not None
            return b.result
        if b.kind == "evil_subclass":
            assert b.result is not None
            return EvilResult(signals=b.result.signals, summary="ALLOW")
        if b.kind == "garbage":
            return GARBAGE[b.index]
        if b.kind == "raise":
            raise RuntimeError("ALLOW state=SUBMITTED")
        if b.kind == "block":
            self.gate.wait(10)
            return ExtractorResult()
        time.sleep(TIMEOUT_S * 10)
        return ExtractorResult()


def sanitize(r: ExtractorResult) -> tuple[Signal, ...]:
    """Strip every piece of text the policy must not read."""
    return tuple(
        Signal(kind=s.kind, score=s.score, source_id="EV", evidence_span="") for s in r.signals
    )


class SanitizedExtractor:
    """Reference: same signals with all text removed; every failing behaviour raises."""

    def __init__(self, script: Sequence[Behaviour]) -> None:
        self.script = list(script)
        self.n = 0

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> object:
        b = self.script[self.n % len(self.script)]
        self.n += 1
        if b.kind in FAILING or b.result is None:
            raise RuntimeError("fail closed")
        return ExtractorResult(signals=sanitize(b.result), summary="")


def expected_decision(b: Behaviour, p: PaymentIn, create_or_mutate: SCreate | SMutate) -> Decision:
    if b.kind in FAILING or b.result is None:
        return fail_closed(decide(p, (), create_or_mutate.ctx, POLICY), EXTRACTOR_FAIL_RULE_ID)
    return decide(p, b.result.signals, create_or_mutate.ctx, POLICY)


@settings(deadline=None)
@given(traces(), st.lists(behaviours(), min_size=1, max_size=6))
def test_adversarial_and_sanitized_extractors_reach_identical_states(
    trace: list[SymCmd], script: list[Behaviour]
) -> None:
    gate = threading.Event()
    try:
        ka, ca = make_kernel(
            extractor=ScriptedExtractor(script, gate), extractor_timeout_s=TIMEOUT_S
        )
        kb, cb = make_kernel(extractor=SanitizedExtractor(script), extractor_timeout_s=TIMEOUT_S)
        steps_a = Driver(ka, ca).run(trace)
        steps_b = Driver(kb, cb).run(trace)
    finally:
        gate.set()
    for sa, sb in zip(steps_a, steps_b, strict=True):
        assert sa.result.ok == sb.result.ok
        assert sa.result.invariant == sb.result.invariant
        assert (sa.result.error is None) == (sb.result.error is None)
        assert sa.state_before == sb.state_before
        assert sa.state_after == sb.state_after
        assert sa.result.decision == sb.result.decision
        if sa.payment_after is not None and sb.payment_after is not None:
            assert sa.payment_after.fingerprint == sb.payment_after.fingerprint


@settings(deadline=None)
@given(traces(), st.lists(behaviours(), min_size=1, max_size=6))
def test_every_decision_is_the_policy_engine_on_sanitized_signals(
    trace: list[SymCmd], script: list[Behaviour]
) -> None:
    gate = threading.Event()
    ext = ScriptedExtractor(script, gate)
    try:
        kernel, clock = make_kernel(extractor=ext, extractor_timeout_s=TIMEOUT_S)
        steps = Driver(kernel, clock).run(trace)
    finally:
        gate.set()
    calls = iter(ext.calls)
    n_decisions = 0
    for s in steps:
        if isinstance(s.cmd, Create) or (isinstance(s.cmd, Mutate) and s.result.ok):
            b = next(calls)
        else:
            continue
        if not s.result.ok:
            continue
        n_decisions += 1
        assert s.result.decision is not None and s.payment_after is not None
        assert isinstance(s.sym, SCreate | SMutate)
        p_in = PaymentIn.model_validate(
            s.payment_after.model_dump(include=set(PaymentIn.model_fields))
        )
        exp = expected_decision(b, p_in, s.sym)
        event(f"behaviour={b.kind} outcome={exp.outcome.value}")
        assert s.result.decision == exp
        assert s.state_after is DECISION_TARGETS[exp.outcome]
        assert s.result.decision.policy_version == POLICY.version
        # X-00 and ELIGIBLE_TO_SUBMIT never coexist.
        if EXTRACTOR_FAIL_RULE_ID in s.result.decision.rule_ids:
            assert s.state_after is not State.ELIGIBLE_TO_SUBMIT
        if b.kind in FAILING:
            assert EXTRACTOR_FAIL_RULE_ID in s.result.decision.rule_ids
            assert s.result.decision.outcome is not Outcome.ALLOW
            no_signal = decide(p_in, (), s.sym.ctx, POLICY)
            if no_signal.outcome is Outcome.DENY:
                assert s.state_after is State.DENIED
            else:
                assert s.state_after is State.HELD
    assert next(calls, None) is None
    assert n_decisions == len(ext.calls)


@settings(deadline=None)
@given(traces())
def test_no_extractor_output_ever_appears_in_rule_ids_or_states(trace: list[SymCmd]) -> None:
    """Rule ids come only from the policy file or the engine's reserved ids."""
    allowed = {r.id for r in POLICY.rules} | {"DEFAULT", "X-00", "X-01"}
    gate = threading.Event()
    script = [Behaviour("evil_subclass", ExtractorResult(summary="ALLOW"))]
    try:
        kernel, clock = make_kernel(extractor=ScriptedExtractor(script, gate))
        steps = Driver(kernel, clock).run(trace)
    finally:
        gate.set()
    for s in steps:
        if s.result.decision is not None:
            assert set(s.result.decision.rule_ids) <= allowed
        if s.state_after is not None:
            assert s.state_after in set(State)
