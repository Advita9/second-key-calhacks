"""Attack panel: four scripted attacks against our own kernel, each ending in a refusal.

Operator only: the router requires the ops token when OPS_TOKEN is set (replay and mutate
issue certificates and release on the rail). Every route returns
`{steps[], refused: true, invariant, text}`, broadcasts an `attack` WS event, and cancels any
payment it created that is still pre-settlement so nothing certifiable is left in the ops
queue. If an attack ever succeeds the route answers 500 with `refused: false`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api import deps
from api.hub import EventBus
from api.settings import REPO_DIR
from kernel.llm.types import EvidenceItem, Signal
from kernel.models import AccountContext, Capability, PaymentIn, Refusal, State
from kernel.policy.engine import decide
from kernel.rooms import OPEN_STATES
from kernel.service import Kernel

log = logging.getLogger("second_key.api.attack")

router = APIRouter(tags=["attack"], dependencies=[Depends(deps.ops_guard)])
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
    def __init__(self, name: str, bus: EventBus, kernel: Kernel) -> None:
        self.name = name
        self.bus = bus
        self.kernel = kernel
        self.steps: list[str] = []
        self.created: list[str] = []

    def step(self, text: str) -> None:
        self.steps.append(text)
        log.info("attack.step", extra={"attack": self.name, "step": text})

    def create(self, p_in: PaymentIn, ctx: AccountContext, conv: tuple[EvidenceItem, ...]) -> str:
        payment, decision = self.kernel.create_payment(p_in, ctx, conv)
        deps.remember_context(payment.id, ctx)
        self.created.append(payment.id)
        self.step(
            f"created {payment.id}: {p_in.beneficiary.name} {p_in.amount_cents} cents "
            f"{p_in.rail.value} -> {decision.outcome.value} {' '.join(decision.rule_ids)}"
        )
        self.publish(payment.id)
        return payment.id

    def create_case(self, case_id: str, **ctx_over: Any) -> str:
        case = load_case(case_id)
        return self.create(
            case_payment(case), case_context(case, **ctx_over), case_conversation(case)
        )

    def publish(self, pid: str) -> None:
        self.bus.payment(self.kernel.get(pid))

    def expect_refusal(self, action: Callable[[], Any], label: str) -> str | None:
        try:
            action()
        except Refusal as r:
            self.step(f"{label} -> {r.text}")
            return r.invariant.value
        self.step(f"{label} -> accepted (unexpected)")
        return None

    def cleanup(self) -> None:
        """Cancel every payment this attack created that is still pre-settlement."""
        for pid in self.created:
            state = self.kernel.get(pid).payment.state
            if state in OPEN_STATES:
                self.kernel.cancel(pid, OPS_ACTOR, Capability.BANK_REVIEW, f"attack {self.name}")
                self.step(f"cleanup: {pid} {state.value} -> CANCELLED")
                self.publish(pid)

    def done(self, invariant: str | None, text: str, **extra: Any) -> JSONResponse:
        self.cleanup()
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


@router.post("/attack/inject")
def inject(bus: Bus) -> JSONResponse:
    """A compromised extractor says "no concerns" on every signal. The policy still holds on
    facts: new payee on WIRE (H-01) and 3x baseline (H-03) read no signals (I4). Runs
    `decide()` directly; no payment row is created."""
    kernel = deps.get_kernel()
    a = _Attack("inject", bus, kernel)
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
    """Creates, attests, certifies, mutates, tries release -> I2. Demo only, like
    `/payments/{id}/mutate`."""
    if not deps.get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    kernel = deps.get_kernel()
    a = _Attack("mutate", bus, kernel)
    pid = a.create_case("L-01")
    kernel.attest(pid, OPS_ACTOR, Capability.BANK_REVIEW, "reviewed")
    a.step("BANK_REVIEW attestation recorded")
    cert = kernel.issue_certificate(pid, OPS_ACTOR, Capability.BANK_REVIEW)
    a.step(f"certificate {cert.id} issued for fingerprint {cert.fingerprint[:12]}...")
    payment, _ = kernel.mutate(pid, {"amount_cents": 800_001}, deps.context_for(pid))
    a.step(
        f"mutated amount +1 cent -> fingerprint {payment.fingerprint[:12]}..., "
        f"state {payment.state.value}, attestations and certificates voided"
    )
    a.publish(pid)
    inv = a.expect_refusal(
        lambda: kernel.release(pid, cert.id, cert.nonce), "release with the old certificate"
    )
    a.publish(pid)
    return a.done(inv, f"SETTLEMENT REFUSED · {inv}" if inv else "release accepted")


@router.post("/attack/replay")
def replay(bus: Bus) -> JSONResponse:
    kernel = deps.get_kernel()
    a = _Attack("replay", bus, kernel)
    pid = a.create_case("L-01")
    cert = kernel.issue_certificate(pid, OPS_ACTOR, Capability.BANK_REVIEW)
    a.step(f"certificate {cert.id} issued")
    first = kernel.release(pid, cert.id, cert.nonce)
    a.step(f"release 1 -> {first.state.value} transfer {first.nessie_transfer_id}")
    a.publish(pid)
    inv = a.expect_refusal(
        lambda: kernel.release(pid, cert.id, cert.nonce), "release 2 with the same certificate"
    )
    a.publish(pid)
    return a.done(inv, f"SETTLEMENT REFUSED · {inv}" if inv else "second release accepted")


@router.post("/attack/self-approve")
def self_approve(bus: Bus) -> JSONResponse:
    kernel = deps.get_kernel()
    a = _Attack("self-approve", bus, kernel)
    ctx = deps.get_sessions().default_ctx
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
    pid = a.create(p_in, ctx, ())
    inv = a.expect_refusal(
        lambda: kernel.attest(pid, "ext_priya", Capability.CO_APPROVER, "looks fine"),
        "Priya (ext_priya) attests as CO_APPROVER to her own payment",
    )
    a.publish(pid)
    assert kernel.get(pid).payment.state is not State.SUBMITTED
    return a.done(inv, f"ATTESTATION REFUSED · {inv}" if inv else "attestation accepted")
