"""Domain models. All frozen, strict Pydantic. No behaviour beyond validation."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator

_DROPPED_CATEGORIES = frozenset({"Cf", "Cc", "Zs"})


def normalize_ref(s: str) -> str:
    """Canonical form for account references and actor ids: NFKC, strip, drop format /
    control / space characters inside, casefold. So `EXT_PRIYA`, `ext_priya ` and
    `ext_priya\u200b` are one ref. NFKC does NOT fold Cyrillic/Greek homoglyphs onto Latin:
    those are different refs, which is acceptable because refs are bank account identifiers,
    not display names (docs/DECISIONS.md).
    """
    out = unicodedata.normalize("NFKC", s).strip()
    out = "".join(ch for ch in out if unicodedata.category(ch) not in _DROPPED_CATEGORIES)
    return out.casefold()


def _validated_ref(value: str, what: str) -> str:
    out = normalize_ref(value)
    if not out:
        raise ValueError(f"{what} is empty after normalization")
    return out


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class Rail(StrEnum):
    WIRE = "WIRE"
    ACH = "ACH"
    ZELLE = "ZELLE"
    CARD = "CARD"
    CRYPTO = "CRYPTO"


class State(StrEnum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    HELD = "HELD"
    ELIGIBLE_TO_SUBMIT = "ELIGIBLE_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class Outcome(StrEnum):
    ALLOW = "ALLOW"
    HOLD = "HOLD"
    DENY = "DENY"


class Capability(StrEnum):
    CUSTOMER_CHECKIN = "CUSTOMER_CHECKIN"
    CO_APPROVER = "CO_APPROVER"
    BANK_REVIEW = "BANK_REVIEW"


class Invariant(StrEnum):
    I1_NO_CERT = "I1_NO_CERT"
    I1_NOT_ELIGIBLE = "I1_NOT_ELIGIBLE"
    I2_FINGERPRINT = "I2_FINGERPRINT"
    I3_REPLAY = "I3_REPLAY"
    I3_EXPIRED = "I3_EXPIRED"
    I5_CONFLICT = "I5_CONFLICT"
    I6_DENIED = "I6_DENIED"


class Beneficiary(StrictModel):
    name: str
    account_ref: str = Field(min_length=1)
    is_new: bool

    @field_validator("account_ref", mode="after")
    @classmethod
    def _norm_ref(cls, v: str) -> str:
        return _validated_ref(v, "account_ref")


class PaymentIn(StrictModel):
    account_id: str = Field(min_length=1)
    amount_cents: PositiveInt
    currency: str = Field(default="USD", min_length=3, max_length=3)
    beneficiary: Beneficiary
    rail: Rail
    conversation_id: str

    @field_validator("account_id", mode="after")
    @classmethod
    def _norm_account(cls, v: str) -> str:
        return _validated_ref(v, "account_id")


class Payment(PaymentIn):
    id: str = Field(min_length=1)
    state: State
    fingerprint: str = Field(min_length=64, max_length=64)
    policy_version: str
    created_at: datetime
    nessie_transfer_id: str | None = None


class AccountContext(StrictModel):
    baseline_90d_cents: int = Field(ge=0)
    known_billers: list[str]
    prior_payees: list[str]
    mule_list: list[str]
    known_biller_cap_cents: int = Field(default=1_500_000, ge=0)

    @field_validator("prior_payees", "mule_list", mode="after")
    @classmethod
    def _norm_refs(cls, v: list[str]) -> list[str]:
        return [normalize_ref(x) for x in v]


class Attestation(StrictModel):
    id: str
    payment_id: str
    actor_id: str
    capability: Capability
    fingerprint: str
    note: str | None
    created_at: datetime
    voided_at: datetime | None


class Certificate(StrictModel):
    id: str
    payment_id: str
    fingerprint: str
    policy_version: str
    actor_id: str
    capability: Capability
    nonce: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    voided_at: datetime | None


class Decision(StrictModel):
    outcome: Outcome
    rule_ids: tuple[str, ...]
    policy_version: str


class Refusal(Exception):
    """Raised by the kernel when an invariant blocks an action. Safe to show to attackers."""

    def __init__(self, invariant: Invariant, detail: str | None = None) -> None:
        self.invariant = invariant
        self.detail = detail
        super().__init__(self.text)

    @property
    def text(self) -> str:
        return f"SETTLEMENT REFUSED · {self.invariant.value}"
