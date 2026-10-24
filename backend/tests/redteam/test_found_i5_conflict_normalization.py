"""FOUND, then FIXED (02405d8 normalize_ref; now green): the I5 self-approval guard compared
actor_id to the beneficiary ref with a bare `==`, with no normalization, so the beneficiary
could co-approve their own payment by adding an
invisible character or changing case.

I5: "A co-approver who is the beneficiary cannot attest." `attest_mod.conflict` is the only gate:

    if actor_id == payment.beneficiary.account_ref:
        return Invariant.I5_CONFLICT

A beneficiary whose ref is `ext_priya` is refused when she attests as `ext_priya`. But she is
ACCEPTED as `ext_priya ` (trailing space), `ext_priya​` (zero-width space), or `EXT_PRIYA`
(case). The attestation is stored and shown as a valid CO_APPROVER co-approval on her own
payment, which I5 forbids.

Impact is bounded: CO_APPROVER cannot lift a hold, issue a certificate, or release, so this
alone moves no money. But it defeats the stated invariant and manufactures false social proof
(a beneficiary "co-approving" themselves) that an operator may rely on. The fix is to normalize
(casefold + strip + strip zero-width) both sides before comparing, the same way any mule-list or
known-biller match should be hardened.

Asserts the SECURE behaviour (these must refuse with I5_CONFLICT), so it is RED today.
"""

from __future__ import annotations

import pytest

from kernel.models import Beneficiary, Capability, Rail, Refusal
from kernel.policy.engine import V1_PATH, load_policy
from kernel.service import Kernel
from tests.factories import account_context, payment_in

# Visually/semantically "the same" beneficiary ref with an invisible or case tweak.
LOOKALIKE_REFS = [
    "ext_priya ",  # trailing space
    " ext_priya",  # leading space
    "ext_priya​",  # zero-width space
    "EXT_PRIYA",  # case fold
]


def _held_payment_to_priya() -> tuple[Kernel, str]:
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH))
    ctx = account_context(prior_payees=["ext_priya"], mule_list=[])
    p_in = payment_in(
        amount_cents=250_000,
        beneficiary=Beneficiary(name="Priya", account_ref="ext_priya", is_new=False),
    )
    payment, _ = kernel.create_payment(p_in, ctx)
    return kernel, payment.id


def test_exact_beneficiary_ref_is_refused() -> None:
    kernel, pid = _held_payment_to_priya()
    with pytest.raises(Refusal) as e:
        kernel.attest(pid, "ext_priya", Capability.CO_APPROVER, "looks fine")
    assert e.value.invariant.value == "I5_CONFLICT"


@pytest.mark.parametrize("actor_id", LOOKALIKE_REFS)
def test_beneficiary_cannot_self_approve_via_lookalike_ref(actor_id: str) -> None:
    kernel, pid = _held_payment_to_priya()
    # SECURE expectation: the beneficiary is still the beneficiary under a trivial disguise.
    with pytest.raises(Refusal) as e:
        kernel.attest(pid, actor_id, Capability.CO_APPROVER, "looks fine")
    assert e.value.invariant.value == "I5_CONFLICT", (
        f"I5 BYPASS: beneficiary self-approved as {actor_id!r}; attestation was accepted"
    )
    assert kernel.get(pid).attestations == []


def test_lookalike_refs_share_one_fingerprint() -> None:
    """Regression for the fix (02405d8): `normalize_ref` runs in the models, so case, edge
    whitespace and zero-width characters collapse to one canonical ref and one fingerprint
    (I2 binds certificates to the canonical ref, not to the spelling)."""
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH))
    ctx = account_context(prior_payees=["ext_priya"], mule_list=[])
    fingerprints: set[str] = set()
    for ref in ("ext_priya", *LOOKALIKE_REFS):
        p_in = payment_in(
            amount_cents=250_000,
            beneficiary=Beneficiary(name="Priya", account_ref=ref, is_new=False),
        )
        assert p_in.beneficiary.account_ref == "ext_priya"
        payment, _ = kernel.create_payment(p_in, ctx)
        fingerprints.add(payment.fingerprint)
    assert len(fingerprints) == 1


def test_lookalike_mule_ref_is_denied_after_normalization() -> None:
    """When found, `ext_9f31 ` dodged D-01 (HELD via H-01, not DENIED). Now it is the mule."""
    kernel = Kernel(":memory:", policy=load_policy(V1_PATH))
    ctx = account_context(mule_list=["ext_9f31"])
    for ref in ("ext_9f31 ", "EXT_9F31", "ext_9f31​"):
        p_in = payment_in(
            amount_cents=50_000,
            beneficiary=Beneficiary(name="Agent", account_ref=ref, is_new=True),
            rail=Rail.WIRE,
        )
        _, decision = kernel.create_payment(p_in, ctx)
        assert decision.outcome.value == "DENY" and "D-01" in decision.rule_ids
