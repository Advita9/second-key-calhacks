"""Policy evaluation environment: the closed set of names a `when` clause may read."""

from __future__ import annotations

from collections.abc import Sequence

from kernel.llm.types import SIGNAL_KINDS, Signal
from kernel.models import AccountContext, PaymentIn

KNOWN_IDENTIFIERS: frozenset[str] = frozenset(
    {
        "amount_cents",
        "currency",
        "rail",
        "baseline_90d_cents",
        "known_biller_cap_cents",
        "beneficiary.is_new",
        "beneficiary.is_known_biller",
        "beneficiary.on_mule_list",
        "signals.count",
        *(f"signals.{kind}" for kind in SIGNAL_KINDS),
    }
)


def build_env(p: PaymentIn, signals: Sequence[Signal], ctx: AccountContext) -> dict[str, object]:
    """Pure. Keys are exactly KNOWN_IDENTIFIERS (tested).

    - is_known_biller: name in known_billers OR account_ref in prior_payees.
    - on_mule_list: account_ref in mule_list. Never by name; names can be spoofed.
    - signals.<kind>: max score among signals of that kind, 0.0 if none.
    """
    maxes: dict[str, float] = dict.fromkeys(SIGNAL_KINDS, 0.0)
    for s in signals:
        if s.score > maxes[s.kind]:
            maxes[s.kind] = s.score
    env: dict[str, object] = {
        "amount_cents": p.amount_cents,
        "currency": p.currency,
        "rail": p.rail.value,
        "baseline_90d_cents": ctx.baseline_90d_cents,
        "known_biller_cap_cents": ctx.known_biller_cap_cents,
        "beneficiary.is_new": p.beneficiary.is_new,
        "beneficiary.is_known_biller": (
            p.beneficiary.name in ctx.known_billers or p.beneficiary.account_ref in ctx.prior_payees
        ),
        "beneficiary.on_mule_list": p.beneficiary.account_ref in ctx.mule_list,
        "signals.count": len(signals),
    }
    for kind in SIGNAL_KINDS:
        env[f"signals.{kind}"] = maxes[kind]
    return env
