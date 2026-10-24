"""Fingerprint: sha256 over canonical JSON of the fields that move money (I2)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from kernel.models import PaymentIn

FINGERPRINT_FIELDS: tuple[str, ...] = (
    "account_id",
    "amount_cents",
    "currency",
    "beneficiary_account_ref",
    "rail",
    "policy_version",
)


def _default(o: object) -> str:
    if isinstance(o, datetime | date):
        return o.isoformat()
    return str(o)


def canonical_json(doc: object) -> str:
    """Stable JSON: sorted keys, no whitespace, datetimes as ISO 8601, anything else via str()."""
    return json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_default
    )


def fingerprint(p: PaymentIn, policy_version: str) -> str:
    doc = {
        "account_id": p.account_id,
        "amount_cents": p.amount_cents,
        "currency": p.currency,
        "beneficiary_account_ref": p.beneficiary.account_ref,
        "rail": p.rail.value,
        "policy_version": policy_version,
    }
    return hashlib.sha256(canonical_json(doc).encode("utf-8")).hexdigest()
