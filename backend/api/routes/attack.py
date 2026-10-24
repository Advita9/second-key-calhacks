"""Attack panel: four scripted attacks against our own kernel, each ending in a refusal.

Every route returns `{steps[], refused: true, invariant, text}` and broadcasts an `attack`
WS event. If an attack ever succeeds the route answers 500 with `refused: false`; the
acceptance tests treat that as a kernel bug.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api import deps
from api.hub import EventBus
from api.settings import REPO_DIR
from kernel.llm.types import EvidenceItem, Signal
from kernel.models import AccountContext, Capability, PaymentIn, Refusal
from kernel.policy.engine import decide
from kernel.service import Kernel

log = logging.getLogger("second_key.api.attack")

router = APIRouter(tags=["attack"])
Bus = Annotated[EventBus, Depends(deps.get_bus)]

CASES_DIR = REPO_DIR / "fixtures" / "cases"
COMPROMISED = REPO_DIR / "fixtures" / "compromised_extractor.json"
OPS_ACTOR = "ops_demo"


def load_case(case_id: str) -> dict[str, Any]:
    raw = json.loads((CASES_DIR / f"{case_id}.json").read_text("utf-8"))
    assert isinstance(raw, dict)
    return raw


def case_payment(case: dict[str, Any]) -> PaymentIn:
    return PaymentIn.model_validate(
        {**case["payment"], "conversation_id": f"case_{case['id']}"}, strict=False
    )


def case_context(case: dict[str, Any], **over: Any) -> AccountContext:
    return AccountContext.model_validate({**case["account_context"], **over}, strict=False)


def case_conversation(case: dict[str, Any]) -> tuple[EvidenceItem, ...]:
    return tuple(EvidenceItem.model_validate(e) for e in case["conversation"])


def load_compromised(path: Path = COMPROMISED) -> tuple[list[Signal], str, str]:
    raw = json.loads(path.read_text("utf-8"))
    signals = [Signal.model_validate(s) for s in raw["signals"]]
    return signals, str(raw.get("summary", "")), str(raw.get("label", "COMPROMISED FIXTURE"))


class _Attack:
    def __init__(self, name: str, bus: EventBus) -> None:
        self.name = name
        self.bus = bus
        self.steps: list[str] = []

    def step(self, text: str) -> None:
        self.steps.append(text)
        log.info("attack.step", extra={"attack": self.name, "step": text})

    def done(self, invariant: str | None, text: str, **extra: Any) -> JSONResponse:
        refused = invariant is not None
        self.bus.attack(self.name, invariant)
        body = {
            "name": self.name,
            "steps": self.steps,
            "refused": refused,
            "invariant": invariant,
            "text": text,
            **extra,
        }
        if not refused:
            log.error("attack.succeeded", extra={"attack": self.name})
        return JSONResponse(body, status_code=200 if refused else 500)


def _expect_refusal(a: _Attack, action: Callable[[], Any], label: str) -> str | None:
    try:
        action()
    except Refusal as r:
        a.step(f"{label} -> {r.text}")
        return r.invariant.value
    a.step(f"{label} -> accepted (unexpected)")
    return None


def _create(a: _Attack, kernel: Kernel, case_id: str, **ctx_over: Any) -> tuple[str, str]:
    case = load_case(case_id)
    p_in = case_payment(case)
    ctx = case_context(case, **ctx_over)
    payment, decision = kernel.create_payment(p_in, ctx, case_conversation(case))
    deps.remember_context(payment.id, ctx)
    a.step(
        f"created {payment.id}: {p_in.beneficiary.name} {p_in.amount_cents} cents "
        f"{p_in.rail.value} -> {decision.outcome.value} {' '.join(decision.rule_ids)}"
    )
    a.bus.payment(kernel.get(payment.id))
    return payment.id, decision.outcome.value


@router.post("/attack/inject")
def inject(bus: Bus) -> JSONResponse:
    """A compromised extractor says "no concerns" on every signal. The policy still holds on
    facts: new payee on WIRE (H-01) and 3x baseline (H-03) read no signals (I4)."""
    a = _Attack("inject", bus)
    kernel = deps.get_kernel()
    signals, summary, label = load_compromised()
    case = load_case("S-03")
    p_in = case_payment(case)
    ctx = case_context(case, mule_list=[])
    a.step(f"loaded {label}: {len(signals)} signals, every score 0.0, summary '{summary}'")
    a.step(
        f"payment: {p_in.beneficiary.name} {p_in.amount_cents} cents {p_in.rail.value}, "
        f"new payee, baseline {ctx.baseline_90d_cents} cents, mule list empty"
    )
    decision = decide(p_in, signals, ctx, kernel.policy)
    rules = " ".join(decision.rule_ids)
    a.step(f"policy {decision.policy_version} decide() -> {decision.outcome.value} {rules}")
    invariant = "POLICY_HOLD" if decision.outcome.value != "ALLOW" else None
    return a.done(
        invariant,
        f"{'HELD' if decision.outcome.value == 'HOLD' else decision.outcome.value} · {rules} "
        "(model said no concerns)",
        decision=decision.outcome.value,
        rule_ids=list(decision.rule_ids),
    )


@router.post("/attack/mutate")
def mutate(bus: Bus) -> JSONResponse:
    a = _Attack("mutate", bus)
    kernel = deps.get_kernel()
    pid, _ = _create(a, kernel, "L-01")
    cert = kernel.issue_certificate(pid, OPS_ACTOR, Capability.BANK_REVIEW)
    a.step(f"certificate {cert.id} issued for fingerprint {cert.fingerprint[:12]}...")
    payment, decision = kernel.mutate(pid, {"amount_cents": 800_001}, deps.context_for(pid))
    a.step(
        f"mutated amount +1 cent -> fingerprint {payment.fingerprint[:12]}..., "
        f"state {payment.state.value}, certificates voided"
    )
    bus.payment(kernel.get(pid))
    inv = _expect_refusal(
        a, lambda: kernel.release(pid, cert.id, cert.nonce), "release with the old certificate"
    )
    bus.payment(kernel.get(pid))
    return a.done(inv, f"SETTLEMENT REFUSED · {inv}" if inv else "release accepted")


@router.post("/attack/replay")
def replay(bus: Bus) -> JSONResponse:
    a = _Attack("replay", bus)
    kernel = deps.get_kernel()
    pid, _ = _create(a, kernel, "L-01")
    cert = kernel.issue_certificate(pid, OPS_ACTOR, Capability.BANK_REVIEW)
    a.step(f"certificate {cert.id} issued")
    first = kernel.release(pid, cert.id, cert.nonce)
    a.step(f"release 1 -> {first.state.value} transfer {first.nessie_transfer_id}")
    bus.payment(kernel.get(pid))
    inv = _expect_refusal(
        a, lambda: kernel.release(pid, cert.id, cert.nonce), "release 2 with the same certificate"
    )
    bus.payment(kernel.get(pid))
    return a.done(inv, f"SETTLEMENT REFUSED · {inv}" if inv else "second release accepted")


@router.post("/attack/self-approve")
def self_approve(bus: Bus) -> JSONResponse:
    a = _Attack("self-approve", bus)
    kernel = deps.get_kernel()
    sessions = deps.get_sessions()
    ctx = sessions.default_ctx
    p_in = PaymentIn.model_validate(
        {
            "account_id": "acc_margaret",
            "amount_cents": 250_000,
            "currency": "USD",
            "beneficiary": {"name": "Priya", "account_ref": "ext_priya", "is_new": False},
            "rail": "ACH",
            "conversation_id": "attack_self_approve",
        },
        strict=False,
    )
    payment, decision = kernel.create_payment(p_in, ctx, ())
    deps.remember_context(payment.id, ctx)
    a.step(
        f"created {payment.id}: 250000 cents ACH to ext_priya -> "
        f"{decision.outcome.value} {' '.join(decision.rule_ids)}"
    )
    bus.payment(kernel.get(payment.id))
    inv = _expect_refusal(
        a,
        lambda: kernel.attest(payment.id, "ext_priya", Capability.CO_APPROVER, "looks fine"),
        "Priya (ext_priya) attests as CO_APPROVER to her own payment",
    )
    bus.payment(kernel.get(payment.id))
    return a.done(inv, f"ATTESTATION REFUSED · {inv}" if inv else "attestation accepted")
