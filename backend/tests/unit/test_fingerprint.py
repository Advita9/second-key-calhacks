"""I2: the fingerprint binds exactly the money-moving fields."""

from __future__ import annotations

import hashlib
import json

from kernel.fingerprint import FINGERPRINT_FIELDS, fingerprint
from kernel.models import Beneficiary, Rail
from tests.factories import payment_in


def test_deterministic() -> None:
    assert fingerprint(payment_in(), "v1") == fingerprint(payment_in(), "v1")


def test_is_sha256_hex() -> None:
    fp = fingerprint(payment_in(), "v1")
    assert len(fp) == 64 and int(fp, 16) >= 0


def test_canonical_json_is_what_is_hashed() -> None:
    p = payment_in()
    doc = {
        "account_id": p.account_id,
        "amount_cents": p.amount_cents,
        "beneficiary_account_ref": p.beneficiary.account_ref,
        "currency": p.currency,
        "policy_version": "v1",
        "rail": "ACH",
    }
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    assert fingerprint(p, "v1") == hashlib.sha256(raw).hexdigest()
    assert set(doc) == set(FINGERPRINT_FIELDS)


def test_each_bound_field_changes_it() -> None:
    base = fingerprint(payment_in(), "v1")
    ben = payment_in().beneficiary
    variants = [
        fingerprint(payment_in(account_id="acc_other"), "v1"),
        fingerprint(payment_in(amount_cents=800_001), "v1"),
        fingerprint(payment_in(currency="EUR"), "v1"),
        fingerprint(
            payment_in(
                beneficiary=Beneficiary(name=ben.name, account_ref="ext_x", is_new=ben.is_new)
            ),
            "v1",
        ),
        fingerprint(payment_in(rail=Rail.WIRE), "v1"),
        fingerprint(payment_in(), "v2"),
    ]
    assert base not in variants
    assert len(set(variants)) == len(variants)


def test_name_and_conversation_do_not_change_it() -> None:
    base = fingerprint(payment_in(), "v1")
    ben = payment_in().beneficiary
    renamed = payment_in(
        beneficiary=Beneficiary(name="Bay R00fing", account_ref=ben.account_ref, is_new=True)
    )
    assert fingerprint(renamed, "v1") == base
    assert fingerprint(payment_in(conversation_id="conv_other"), "v1") == base


def test_lookalike_refs_share_one_fingerprint() -> None:
    base = fingerprint(payment_in(), "v1")
    for ref in (
        "EXT_BAY_ROOFING",
        " ext_bay_roofing",
        "ext_bay_roofing\u200b",
        "ext_bay_roofing\t",
    ):
        same = payment_in(beneficiary=Beneficiary(name="x", account_ref=ref, is_new=True))
        assert same.beneficiary.account_ref == "ext_bay_roofing"
        assert fingerprint(same, "v1") == base
    assert payment_in(account_id="ACC_MARGARET ").account_id == "acc_margaret"
    assert fingerprint(payment_in(account_id="ACC_MARGARET "), "v1") == base


def test_ref_that_normalizes_to_empty_is_rejected() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Beneficiary(name="x", account_ref=" \u200b ", is_new=True)
    with pytest.raises(ValidationError):
        payment_in(account_id="\u200b")
