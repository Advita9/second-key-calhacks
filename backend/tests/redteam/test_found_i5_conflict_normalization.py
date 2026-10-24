"""FOUND (red): the I5 self-approval guard compares actor_id to the beneficiary ref with a bare
`==`, with no normalization, so the beneficiary can co-approve their own payment by adding an
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

from kernel.models import Beneficiary, Capability, Refusal
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
