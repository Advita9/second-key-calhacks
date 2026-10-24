"""Policy evaluation environment: the closed set of names a `when` clause may read."""

from __future__ import annotations

from collections.abc import Sequence

from kernel.llm.types import SIGNAL_KINDS, Signal
from kernel.models import AccountContext, Beneficiary, PaymentIn, Rail

KNOWN_IDENTIFIERS: frozenset[str] = frozenset(
    {
        "amount_cents",
        "currency",
        "rail",
        "baseline_90d_cents",
        "known_biller_cap_cents",
        "beneficiary.is_new",
        "beneficiary.is_known_biller",
        "beneficiary.name_on_biller_list",
        "beneficiary.on_mule_list",
        "signals.count",
        *(f"signals.{kind}" for kind in SIGNAL_KINDS),
    }
)


def build_env(p: PaymentIn, signals: Sequence[Signal], ctx: AccountContext) -> dict[str, object]:
    """Pure. Keys are exactly KNOWN_IDENTIFIERS (tested).

    - is_new: the caller's flag OR account_ref not in prior_payees. The caller alone is never
      trusted to say a payee is old.
    - is_known_biller: account_ref in prior_payees. ONLY by ref: a display name is attacker
      controlled ("PG&E" with a fresh account_ref must not be trusted).
    - name_on_biller_list: name in known_billers. Informational only; no v1 rule may ALLOW on it.
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
        "beneficiary.is_new": (
            p.beneficiary.is_new or p.beneficiary.account_ref not in ctx.prior_payees
        ),
        "beneficiary.is_known_biller": p.beneficiary.account_ref in ctx.prior_payees,
        "beneficiary.name_on_biller_list": p.beneficiary.name in ctx.known_billers,
        "beneficiary.on_mule_list": p.beneficiary.account_ref in ctx.mule_list,
        "signals.count": len(signals),
    }
    for kind in SIGNAL_KINDS:
        env[f"signals.{kind}"] = maxes[kind]
    return env


def sample_env() -> dict[str, object]:
    """A representative environment used to smoke-evaluate every rule at load time."""
    p = PaymentIn(
        account_id="acc_sample",
        amount_cents=100,
        currency="USD",
        beneficiary=Beneficiary(name="Sample Payee", account_ref="ext_sample", is_new=True),
        rail=Rail.ACH,
        conversation_id="conv_sample",
    )
    ctx = AccountContext(
        baseline_90d_cents=400_000, known_billers=[], prior_payees=[], mule_list=[]
    )
    return build_env(p, [], ctx)
