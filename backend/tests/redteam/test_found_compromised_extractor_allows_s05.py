"""FOUND, then FIXED (02405d8, rule H-07; now green): a compromised / zero-signal extractor let
scam case S-05 reach SUBMITTED.

The attack in the agent brief: "run the 20 scam fixtures with the extractor returning zero
signals; rules alone (H-01, H-03, D-01) must still HOLD or DENY most of them. Report how many
rely on signals." 19 of 20 still HOLD or DENY on facts. Exactly one does not: S-05.

S-05 is a payment to `ext_robert_hale`, a PRIOR payee, $1,500 on ZELLE, under the known-biller
cap and under 3x baseline. With no signals:
  - D-01 (mule list) does not fire: the ref is not on the mule list.
  - H-01 (new payee on WIRE/ZELLE/CRYPTO) does not fire: the payee is not new (prior payee).
  - H-03 (> 3x baseline) does not fire: 150000 <= 3 * 240000.
  - A-01 (known biller by ref, under cap) DOES fire -> ALLOW.
So the only thing that holds S-05 is the extractor's secrecy/urgency signals. The project's own
`fixtures/compromised_extractor.json` claims "the policy engine still HOLDs or DENYs on payment
facts alone"; that claim is false for S-05. A-01 consults no signals, so a model that is prompt
-injected into emitting nothing (which I4 explicitly permits: "zero valid signals is fine")
flips S-05 from HOLD to ALLOW, and an ALLOW is certifiable and releasable -> SUBMITTED.

This asserts the SECURE behaviour (S-05 must not reach SUBMITTED with a blind extractor) and so
is RED against the current kernel. Do not fix the kernel here; this is the finding.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from kernel.clock import FakeClock
from kernel.llm.types import EvidenceItem, NullExtractor
from kernel.models import AccountContext, Capability, Invariant, PaymentIn, Refusal, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.rail import NullTransferRail
from kernel.service import Kernel

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"


def _load(case_id: str) -> dict[str, Any]:
    raw = json.loads((CASES / f"{case_id}.json").read_text("utf-8"))
    assert isinstance(raw, dict)
    return raw


def _kernel() -> Kernel:
    return Kernel(
        ":memory:",
        policy=load_policy(V1_PATH),
        clock=FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC)),
        extractor=NullExtractor(),  # a fully compromised model emits nothing
        rail=NullTransferRail(),
    )


def test_s05_scam_must_not_submit_with_a_blind_extractor() -> None:
    case = _load("S-05")
    assert case["expected"]["outcome"] == "HOLD"
    # Was `signals_required is True` when found; H-07 now holds S-05 on facts alone and the
    # fixture says signals_required=false. The secure expectation below is unchanged.
    assert isinstance(case["signals_required"], bool)
    kernel = _kernel()
    p_in = PaymentIn.model_validate(
        {**case["payment"], "conversation_id": case["id"]}, strict=False
    )
    ctx = AccountContext.model_validate(case["account_context"], strict=False)
    conv = tuple(EvidenceItem.model_validate(e) for e in case["conversation"])

    payment, decision = kernel.create_payment(p_in, ctx, conv)

    # SECURE expectation: a scam must never land in a releasable state when the model is blind.
    assert decision.outcome.value != "ALLOW", (
        f"S-05 decided {decision.outcome.value} {decision.rule_ids} with zero signals: "
        "A-01 allowed a scam because known-biller ALLOW consults no signals"
    )
    assert payment.state is State.HELD

    # And it must not be completable end to end: no certificate can be issued on a HELD
    # payment, so the compromised model has no path to SUBMITTED.
    with pytest.raises(Refusal) as e:
        kernel.issue_certificate(payment.id, "ops", Capability.BANK_REVIEW)
    assert e.value.invariant is Invariant.I1_NOT_ELIGIBLE
    assert kernel.get(payment.id).payment.state is State.HELD


def test_s05_holds_on_facts_with_blind_extractor_via_h07() -> None:
    """Regression for the fix (02405d8): H-07 holds person-to-person transfers on irreversible
    rails above $1,000 on facts alone, so S-05 (prior payee, $1,500 ZELLE) is HELD with zero
    signals and the known-biller ALLOW (A-01) no longer wins."""
    case = _load("S-05")
    kernel = _kernel()
    p_in = PaymentIn.model_validate(
        {**case["payment"], "conversation_id": case["id"]}, strict=False
    )
    ctx = AccountContext.model_validate(case["account_context"], strict=False)
    payment, decision = kernel.create_payment(p_in, ctx, ())
    assert decision.outcome.value == "HOLD"
    assert "H-07" in decision.rule_ids
    assert payment.state is State.HELD
    assert kernel.audit_verify().ok
