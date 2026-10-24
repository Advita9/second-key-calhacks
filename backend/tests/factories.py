"""Small builders shared by unit and property tests. No I/O."""

from __future__ import annotations

from datetime import UTC, datetime

from kernel.fingerprint import fingerprint
from kernel.models import AccountContext, Beneficiary, Payment, PaymentIn, Rail, State

POLICY_VERSION = "v1"
T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def payment_in(**over: object) -> PaymentIn:
    base: dict[str, object] = {
        "account_id": "acc_margaret",
        "amount_cents": 800_000,
        "currency": "USD",
        "beneficiary": Beneficiary(name="Bay Roofing", account_ref="ext_bay_roofing", is_new=False),
        "rail": Rail.ACH,
        "conversation_id": "conv_1",
    }
    base.update(over)
    return PaymentIn.model_validate(base)


def payment(
    pin: PaymentIn | None = None, *, state: State = State.DRAFT, pid: str = "pay_1"
) -> Payment:
    pin = pin or payment_in()
    return Payment(
        **pin.model_dump(),
        id=pid,
        state=state,
        fingerprint=fingerprint(pin, POLICY_VERSION),
        policy_version=POLICY_VERSION,
        created_at=T0,
    )


def account_context(**over: object) -> AccountContext:
    base: dict[str, object] = {
        "baseline_90d_cents": 400_000,
        "known_billers": ["PG&E", "Comcast", "Bay Roofing"],
        "prior_payees": ["ext_bay_roofing", "ext_pge"],
        "mule_list": ["ext_9f31"],
    }
    base.update(over)
    return AccountContext.model_validate(base)
