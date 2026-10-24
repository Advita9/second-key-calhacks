"""FOUND (open, final pass, tested at 48d821a): rule H-07 reads the attacker-controlled display
name, so the S-05 shape (prior payee, person-to-person rail, over $1,000) is ALLOWed by A-01
again as soon as the payee's display name is one of the known biller names.

H-07 was added in 02405d8 to close exactly this gap "on facts alone":

    when: rail in [WIRE, ZELLE, CRYPTO] and not beneficiary.name_on_biller_list
          and amount_cents > 100000

`beneficiary.name_on_biller_list` is `p.beneficiary.name in ctx.known_billers`, an exact match
on the free-text display name. `kernel/policy/env.py` itself says display names are attacker
controlled and that no ALLOW rule may read them; H-07 does not ALLOW, but its ABSENCE is what
lets A-01 win, so a spoofed name has the same effect as an ALLOW rule reading the name.

Reproduction (zero signals, i.e. a blind or injected extractor, which I4 explicitly permits):
  - S-05 as shipped: Robert Hale / ext_robert_hale, $1,500 ZELLE -> HOLD (H-07, A-01). Good.
  - S-05 with beneficiary.name = "PG&E" (ref unchanged, still ext_robert_hale) -> ALLOW (A-01)
    -> ELIGIBLE_TO_SUBMIT -> certificate -> release -> SUBMITTED. The scam completes.
  - Over HTTP, `POST /payments` without any token and without a custom context (the default
    L-01 context) accepts {name: "PG&E", account_ref: "ext_priya", rail: ZELLE, $5,000} and
    answers ALLOW / ELIGIBLE_TO_SUBMIT.

Scope: the room path cannot build this shape (a typed biller name resolves to the biller's own
ref, any other name mints a fresh ref), and release still needs the ops token. The exposure is
the policy layer's "facts alone" claim in fixtures/compromised_extractor.json and the README:
with a blind extractor the mule-free, prior-payee Zelle scam is releasable once the payee
record carries a biller-looking nickname (a coached customer can be told what nickname to
type). With the mock extractor's signals present S-05 still HOLDs on H-02.

Suggested fix (for the lead, not applied here): give the policy a ref-based fact. Either carry
the biller refs in AccountContext (`known_biller_refs`) and define
`beneficiary.is_listed_biller = account_ref in known_biller_refs`, or compute
`name_on_biller_list` only when the ref is the one mapped to that name. Then re-run the 60
fixtures; L-09 and L-39 are the ALLOW cases H-07 must keep ALLOWing.

These tests assert the SECURE behaviour, so they are RED today.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from kernel.clock import FakeClock
from kernel.llm.mock_extractor import MockExtractor
from kernel.llm.types import EvidenceItem, NullExtractor
from kernel.models import AccountContext, Capability, PaymentIn, State
from kernel.policy.engine import V1_PATH, decide, load_policy
from kernel.rail import NullTransferRail
from kernel.service import Kernel

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"
POLICY = load_policy(V1_PATH)


def _load(case_id: str) -> dict[str, Any]:
    raw = json.loads((CASES / f"{case_id}.json").read_text("utf-8"))
    assert isinstance(raw, dict)
    return raw


def _s05(spoof_name: str | None) -> tuple[PaymentIn, AccountContext, tuple[EvidenceItem, ...]]:
    case = _load("S-05")
    ctx = AccountContext.model_validate(case["account_context"], strict=False)
    payment = {**case["payment"], "conversation_id": "S-05"}
    if spoof_name is not None:
        payment["beneficiary"] = {**payment["beneficiary"], "name": spoof_name}
    p_in = PaymentIn.model_validate(payment, strict=False)
    conv = tuple(EvidenceItem.model_validate(e) for e in case["conversation"])
    return p_in, ctx, conv


def _kernel(extractor: object) -> Kernel:
    return Kernel(
        ":memory:",
        policy=POLICY,
        clock=FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC)),
        extractor=extractor,  # type: ignore[arg-type]
        rail=NullTransferRail(),
    )


def test_control_s05_as_shipped_holds_on_facts() -> None:
    """Positive control (green): without the spoof H-07 holds S-05 with zero signals."""
    p_in, ctx, _ = _s05(None)
    d = decide(p_in, [], ctx, POLICY)
    assert d.outcome.value == "HOLD" and "H-07" in d.rule_ids


def test_s05_with_a_biller_display_name_must_still_hold_with_zero_signals() -> None:
    p_in, ctx, _ = _s05(ctx_biller_name())
    assert p_in.beneficiary.account_ref == "ext_robert_hale"  # the ref did not change
    d = decide(p_in, [], ctx, POLICY)
    # SECURE expectation: the display name is not a fact; the hold must survive the spoof.
    assert d.outcome.value != "ALLOW", (
        f"H-07 BYPASS: S-05 with display name {p_in.beneficiary.name!r} decided "
        f"{d.outcome.value} {d.rule_ids} with zero signals"
    )


def test_s05_with_a_biller_display_name_never_reaches_submitted_end_to_end() -> None:
    p_in, ctx, conv = _s05(ctx_biller_name())
    kernel = _kernel(NullExtractor())  # a blind model emits nothing
    payment, decision = kernel.create_payment(p_in, ctx, conv)
    if payment.state is State.ELIGIBLE_TO_SUBMIT:
        cert = kernel.issue_certificate(payment.id, "ops", Capability.BANK_REVIEW)
        kernel.release(payment.id, cert.id, cert.nonce)
    final = kernel.get(payment.id).payment.state
    assert final is not State.SUBMITTED, (
        f"S-05 with a spoofed biller name reached {final.value} "
        f"(decision {decision.outcome.value} {decision.rule_ids})"
    )


def test_with_signals_present_the_spoof_still_holds_on_h02() -> None:
    """Documentation (green): the exposure needs a blind extractor. With the mock extractor's
    secrecy signal from the S-05 transcript the payment HOLDs on H-02."""
    p_in, ctx, conv = _s05(ctx_biller_name())
    _, decision = _kernel(MockExtractor()).create_payment(p_in, ctx, conv)
    assert decision.outcome.value == "HOLD" and "H-02" in decision.rule_ids


def test_open_create_route_allows_zelle_to_a_prior_payee_by_display_name(
    ops_client: TestClient,
) -> None:
    """Over HTTP with OPS_TOKEN set and NO header: the default context already lists ext_priya
    as a prior payee and "PG&E" as a biller name. Naming the payee "PG&E" on ext_priya turns a
    $5,000 Zelle (S-05 shape) into ALLOW / ELIGIBLE_TO_SUBMIT with no credential at all."""
    r = ops_client.post(
        "/payments",
        json={
            "account_id": "acc_margaret",
            "amount_cents": 500_000,
            "currency": "USD",
            "beneficiary": {"name": "PG&E", "account_ref": "ext_priya", "is_new": False},
            "rail": "ZELLE",
            "conversation_id": "rt-final",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"]["outcome"] != "ALLOW", (
        f"open POST /payments: {body['decision']} state={body['state']} for a $5,000 Zelle to "
        "ext_priya labelled 'PG&E'"
    )
    assert body["state"] != "ELIGIBLE_TO_SUBMIT"


def ctx_biller_name() -> str:
    """The first known biller name of the S-05 context (PG&E)."""
    case = _load("S-05")
    billers = case["account_context"]["known_billers"]
    assert isinstance(billers, list) and billers
    return str(billers[0])
