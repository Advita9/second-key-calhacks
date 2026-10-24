"""Request DTOs (lax: plain JSON in) and record serialisers (JSON out).

DTOs are converted into the strict kernel models with `strict=False`, so `"WIRE"` becomes
`Rail.WIRE` and ints arrive as ints. Nothing in a DTO reaches the kernel without that
conversion. Serialisers never include a certificate nonce (the kernel redacts it) and never
include an ops token.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kernel.audit import AuditEvent
from kernel.llm.types import EvidenceItem
from kernel.models import AccountContext, Attestation, Capability, Certificate, PaymentIn
from kernel.rooms import origin_of
from kernel.service import PaymentRecord

MAX_TURN_CHARS = 400  # same cap as the SpacetimeDB submit_turn reducer
MAX_AMOUNT_CENTS = 1_000_000_000_000  # $10B: far above any demo amount, well inside SQLite INTEGER


class Lax(BaseModel):
    model_config = ConfigDict(strict=False, extra="ignore")


class BeneficiaryIn(Lax):
    name: str = Field(min_length=1, max_length=120)
    account_ref: str = Field(min_length=1, max_length=64)
    is_new: bool = False


class EvidenceIn(Lax):
    id: str = Field(min_length=1, max_length=32)
    speaker: str = Field(min_length=1, max_length=32)
    text: str = Field(max_length=4000)

    def to_item(self) -> EvidenceItem:
        return EvidenceItem(id=self.id, speaker=self.speaker, text=self.text)


class AccountContextIn(Lax):
    baseline_90d_cents: int = Field(ge=0)
    known_billers: list[str] = Field(default_factory=list)
    prior_payees: list[str] = Field(default_factory=list)
    mule_list: list[str] = Field(default_factory=list)
    known_biller_cap_cents: int = Field(default=1_500_000, ge=0)

    def to_ctx(self) -> AccountContext:
        return AccountContext.model_validate(self.model_dump(), strict=False)


class PaymentCreate(Lax):
    account_id: str = Field(default="acc_margaret", min_length=1, max_length=64)
    amount_cents: int = Field(gt=0, le=MAX_AMOUNT_CENTS)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    beneficiary: BeneficiaryIn
    rail: str
    conversation_id: str = Field(default="", max_length=64)
    # Extensions beyond docs/api.md, both optional: the transcript to extract from and the
    # account context to decide with. Without them the route uses the room named by
    # conversation_id (its transcript and context) or the default L-01 context.
    conversation: list[EvidenceIn] | None = Field(default=None, max_length=200)
    account_context: AccountContextIn | None = None

    def to_payment_in(self) -> PaymentIn:
        raw = self.model_dump(exclude={"conversation", "account_context"})
        raw["rail"] = raw["rail"].strip().upper()
        return PaymentIn.model_validate(raw, strict=False)


class AttestIn(Lax):
    actor_id: str = Field(min_length=1, max_length=64)
    capability: str
    note: str | None = Field(default=None, max_length=2000)

    def cap(self) -> Capability:
        return Capability(self.capability.strip().upper())


class CertificateIn(Lax):
    actor_id: str = Field(min_length=1, max_length=64)
    capability: str = "BANK_REVIEW"

    def cap(self) -> Capability:
        return Capability(self.capability.strip().upper())


class ReleaseIn(Lax):
    certificate_id: str = Field(min_length=1, max_length=64)
    nonce: str = Field(min_length=1, max_length=128)


class MutateIn(Lax):
    """Partial PaymentIn. Only the fields present become the patch."""

    account_id: str | None = None
    amount_cents: int | None = Field(default=None, gt=0, le=MAX_AMOUNT_CENTS)
    currency: str | None = None
    beneficiary: dict[str, Any] | None = None
    rail: str | None = None
    conversation_id: str | None = None
    account_context: AccountContextIn | None = None

    def patch(self) -> dict[str, Any]:
        raw = self.model_dump(exclude_unset=True, exclude={"account_context"})
        out = {k: v for k, v in raw.items() if v is not None}
        if "rail" in out:
            out["rail"] = str(out["rail"]).strip().upper()
        return out


class DenyIn(Lax):
    actor_id: str = Field(default="ops", min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class TurnIn(Lax):
    turn_id: str | int
    player_id: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=MAX_TURN_CHARS)
    audio_url: str | None = None


# ---------------------------------------------------------------- serialisers


def attestation_dict(a: Attestation) -> dict[str, Any]:
    d = a.model_dump(mode="json")
    d["valid"] = a.voided_at is None
    d["voided"] = a.voided_at is not None
    return d


def certificate_dict(c: Certificate) -> dict[str, Any]:
    d = c.model_dump(mode="json")
    d["consumed"] = c.consumed_at is not None
    d["voided"] = c.voided_at is not None
    return d


def audit_event_dict(e: AuditEvent) -> dict[str, Any]:
    d = e.model_dump(mode="json")
    for k in ("from", "to"):
        if k in e.payload:
            d[k] = e.payload[k]
    return d


def decision_dict(record: PaymentRecord) -> dict[str, Any] | None:
    if record.decision is None:
        return None
    return {
        "outcome": record.decision.outcome.value,
        "rule_ids": list(record.decision.rule_ids),
        "policy_version": record.decision.policy_version,
        "signals": [s.model_dump(mode="json") for s in record.signals],
    }


def last_refusal(record: PaymentRecord) -> str | None:
    for ev in reversed(record.history):
        if ev.kind == "REFUSED":
            inv = ev.payload.get("invariant")
            return str(inv) if inv is not None else None
    return None


def payment_dict(record: PaymentRecord) -> dict[str, Any]:
    """`GET /payments/{id}`: the payment, its decision, attestations, certificates, history."""
    p = record.payment
    return {
        **p.model_dump(mode="json"),
        "decision": decision_dict(record),
        "attestations": [attestation_dict(a) for a in record.attestations],
        "certificates": [certificate_dict(c) for c in record.certificates],
        "history": [audit_event_dict(e) for e in record.history],
        "last_refusal": last_refusal(record),
        "origin": origin_of(p.conversation_id),
    }


def payment_summary(record: PaymentRecord) -> dict[str, Any]:
    """`POST /payments` response per docs/api.md plus the full record for the UI."""
    d = payment_dict(record)
    d["id"] = record.payment.id
    return d
