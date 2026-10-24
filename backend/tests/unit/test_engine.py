"""Policy engine: load-time strictness, precedence, default HOLD, fail-closed paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.llm.types import Signal
from kernel.models import Beneficiary, Decision, Outcome, Rail
from kernel.policy.engine import (
    DEFAULT_RULE_ID,
    EVAL_ERROR_RULE_ID,
    V1_PATH,
    Policy,
    PolicyLoadError,
    decide,
    fail_closed,
    load_policy,
)
from kernel.policy.env import KNOWN_IDENTIFIERS, build_env
from tests.factories import account_context, payment_in

FIXTURES = Path(__file__).parent / "policy_fixtures"


@pytest.fixture(scope="module")
def v1() -> Policy:
    return load_policy(V1_PATH)


def sig(kind: str, score: float) -> Signal:
    return Signal(kind=kind, score=score, source_id="EV-0001", evidence_span="x")  # type: ignore[arg-type]


# loading -----------------------------------------------------------------------------------


def test_v1_loads(v1: Policy) -> None:
    assert v1.version == "v1"
    assert v1.default is Outcome.HOLD
    assert v1.precedence == (Outcome.DENY, Outcome.HOLD, Outcome.ALLOW)
    ids = [r.id for r in v1.rules]
    assert ids == ["D-01", "H-01", "H-02", "H-03", "H-04", "H-05", "H-06", "A-01"]
    assert set(v1.compiled) == set(ids)


def test_v1_uses_only_known_identifiers(v1: Policy) -> None:
    from kernel.policy.expr import free_identifiers

    used = frozenset().union(*(free_identifiers(n) for n in v1.compiled.values()))
    assert used <= KNOWN_IDENTIFIERS


@pytest.mark.parametrize(
    ("name", "needle"),
    [
        ("missing_outcome", "outcome"),
        ("missing_id", "id"),
        ("unknown_identifier", "beneficiary.is_vip"),
        ("default_allow", "default"),
        ("duplicate_id", "H-01"),
        ("bad_outcome", "MAYBE"),
        ("parse_error", "H-01"),
        ("bad_precedence", "precedence"),
        ("reserved_id", "X-01"),
        ("not_a_mapping", "mapping"),
    ],
)
def test_bad_policies_fail_loudly_at_load(name: str, needle: str) -> None:
    with pytest.raises(PolicyLoadError) as ei:
        load_policy(FIXTURES / f"{name}.yaml")
    assert needle in str(ei.value)


def test_missing_file_is_load_error() -> None:
    with pytest.raises(PolicyLoadError):
        load_policy(FIXTURES / "does_not_exist.yaml")


# env ---------------------------------------------------------------------------------------


def test_build_env_keys_are_exactly_known_identifiers() -> None:
    env = build_env(payment_in(), [], account_context())
    assert frozenset(env) == KNOWN_IDENTIFIERS


def test_env_known_biller_by_prior_ref_only_never_name() -> None:
    ctx = account_context()
    by_name = payment_in(
        beneficiary=Beneficiary(name="Comcast", account_ref="ext_new_comcast", is_new=True)
    )
    by_ref = payment_in(
        beneficiary=Beneficiary(name="Whoever", account_ref="ext_pge", is_new=False)
    )
    neither = payment_in(beneficiary=Beneficiary(name="Agent", account_ref="ext_zz", is_new=True))
    assert build_env(by_name, [], ctx)["beneficiary.is_known_biller"] is False
    assert build_env(by_name, [], ctx)["beneficiary.name_on_biller_list"] is True
    assert build_env(by_ref, [], ctx)["beneficiary.is_known_biller"] is True
    assert build_env(by_ref, [], ctx)["beneficiary.name_on_biller_list"] is False
    assert build_env(neither, [], ctx)["beneficiary.is_known_biller"] is False
    assert build_env(neither, [], ctx)["beneficiary.name_on_biller_list"] is False


def test_spoofed_biller_name_with_new_ref_holds_not_allows(v1: Policy) -> None:
    """S-07 class: display name "PG&E" on a fresh account_ref, zero signals, must not ALLOW."""
    p = payment_in(
        amount_cents=100,
        beneficiary=Beneficiary(name="PG&E", account_ref="ext_fresh_1", is_new=True),
        rail=Rail.ACH,
    )
    d = decide(p, [], account_context(), v1)
    assert d.outcome is Outcome.HOLD and d.rule_ids == (DEFAULT_RULE_ID,)


def test_no_v1_rule_reads_name_on_biller_list(v1: Policy) -> None:
    from kernel.policy.expr import free_identifiers

    used = frozenset().union(*(free_identifiers(n) for n in v1.compiled.values()))
    assert "beneficiary.name_on_biller_list" not in used


def test_env_mule_list_matches_account_ref_never_name() -> None:
    ctx = account_context(mule_list=["ext_9f31"], known_billers=["Agent Daniels"])
    by_ref = payment_in(
        beneficiary=Beneficiary(name="Nice Name", account_ref="ext_9f31", is_new=True)
    )
    by_name_only = payment_in(
        beneficiary=Beneficiary(name="ext_9f31", account_ref="ext_other", is_new=True)
    )
    assert build_env(by_ref, [], ctx)["beneficiary.on_mule_list"] is True
    assert build_env(by_name_only, [], ctx)["beneficiary.on_mule_list"] is False


def test_env_signals_are_max_per_kind_and_count() -> None:
    sigs = [sig("urgency", 0.3), sig("urgency", 0.9), sig("threat", 0.2)]
    env = build_env(payment_in(), sigs, account_context())
    assert env["signals.urgency"] == 0.9
    assert env["signals.threat"] == 0.2
    assert env["signals.secrecy"] == 0.0
    assert env["signals.count"] == 3
    assert env["rail"] == "ACH" and env["currency"] == "USD"


# decisions ---------------------------------------------------------------------------------


def test_known_biller_allows(v1: Policy) -> None:
    d = decide(payment_in(), [], account_context(), v1)
    assert d == Decision(outcome=Outcome.ALLOW, rule_ids=("A-01",), policy_version="v1")


def test_no_rule_fires_defaults_to_hold(v1: Policy) -> None:
    p = payment_in(
        amount_cents=100,
        beneficiary=Beneficiary(name="Stranger", account_ref="ext_stranger", is_new=False),
    )
    d = decide(p, [], account_context(), v1)
    assert d.outcome is Outcome.HOLD and d.rule_ids == (DEFAULT_RULE_ID,)


def test_scenario_a_irs_wire_holds_on_h01_and_h03(v1: Policy) -> None:
    p = payment_in(
        amount_cents=1_850_000,
        beneficiary=Beneficiary(name="Agent Daniels", account_ref="ext_new", is_new=True),
        rail=Rail.WIRE,
    )
    d = decide(p, [sig("secrecy", 0.9), sig("authority", 0.8)], account_context(), v1)
    assert d.outcome is Outcome.HOLD
    assert d.rule_ids == ("H-01", "H-02", "H-03")


def test_mule_list_denies_and_deny_wins_over_everything(v1: Policy) -> None:
    p = payment_in(
        amount_cents=100,
        beneficiary=Beneficiary(name="Bay Roofing", account_ref="ext_9f31", is_new=False),
    )
    ctx = account_context(prior_payees=["ext_9f31"])
    d = decide(p, [], ctx, v1)
    assert d.outcome is Outcome.DENY
    assert d.rule_ids[0] == "D-01" and "A-01" in d.rule_ids


def test_hold_wins_over_allow(v1: Policy) -> None:
    d = decide(payment_in(), [sig("secrecy", 0.95)], account_context(), v1)
    assert d.outcome is Outcome.HOLD and d.rule_ids == ("H-02", "A-01")


def test_rule_ids_in_yaml_order(v1: Policy) -> None:
    p = payment_in(
        amount_cents=5_000_000,
        beneficiary=Beneficiary(name="New", account_ref="ext_9f31", is_new=True),
        rail=Rail.CRYPTO,
    )
    sigs = [
        sig("secrecy", 0.9),
        sig("urgency", 0.9),
        sig("authority", 0.9),
        sig("payment_method", 0.9),
        sig("threat", 0.9),
    ]
    d = decide(p, sigs, account_context(), v1)
    assert d.rule_ids == ("D-01", "H-01", "H-02", "H-03", "H-04", "H-05", "H-06")


@pytest.mark.parametrize(
    ("rule", "sigs", "rail", "is_new"),
    [
        ("H-04", [("urgency", 0.8)], Rail.ACH, True),
        ("H-05", [("authority", 0.7), ("payment_method", 0.5)], Rail.ACH, False),
        ("H-06", [("threat", 0.7)], Rail.ACH, False),
    ],
)
def test_signal_rules(
    v1: Policy, rule: str, sigs: list[tuple[str, float]], rail: Rail, is_new: bool
) -> None:
    p = payment_in(
        amount_cents=100,
        beneficiary=Beneficiary(name="Someone", account_ref="ext_s", is_new=is_new),
        rail=rail,
    )
    d = decide(p, [sig(k, s) for k, s in sigs], account_context(), v1)
    assert d.outcome is Outcome.HOLD and d.rule_ids == (rule,)


def test_h01_new_payee_on_irreversible_rail_only(v1: Policy) -> None:
    for rail, expect in [
        (Rail.WIRE, True),
        (Rail.ZELLE, True),
        (Rail.CRYPTO, True),
        (Rail.ACH, False),
        (Rail.CARD, False),
    ]:
        p = payment_in(
            amount_cents=100,
            beneficiary=Beneficiary(name="New", account_ref="ext_n", is_new=True),
            rail=rail,
        )
        d = decide(p, [], account_context(), v1)
        assert ("H-01" in d.rule_ids) is expect, rail


def test_known_biller_over_cap_is_not_allowed(v1: Policy) -> None:
    d = decide(
        payment_in(amount_cents=1_500_001), [], account_context(baseline_90d_cents=10**9), v1
    )
    assert d.outcome is Outcome.HOLD and d.rule_ids == (DEFAULT_RULE_ID,)


# fail closed ---------------------------------------------------------------------------------


def test_eval_error_holds_with_x01() -> None:
    pol = load_policy(FIXTURES / "eval_error.yaml")
    d = decide(payment_in(), [], account_context(), pol)
    assert d.outcome is Outcome.HOLD
    assert EVAL_ERROR_RULE_ID in d.rule_ids and "A-01" in d.rule_ids
    assert d.policy_version == "evalerr"


def test_eval_error_never_lowers_a_deny() -> None:
    pol = load_policy(FIXTURES / "eval_error.yaml")
    p = payment_in(beneficiary=Beneficiary(name="x", account_ref="ext_9f31", is_new=False))
    d = decide(p, [], account_context(), pol)
    assert d.outcome is Outcome.DENY and d.rule_ids[:2] == ("D-01", EVAL_ERROR_RULE_ID)


def test_non_bool_when_is_eval_error() -> None:
    pol = load_policy(FIXTURES / "non_bool.yaml")
    d = decide(payment_in(), [], account_context(), pol)
    assert d.outcome is Outcome.HOLD and d.rule_ids == (EVAL_ERROR_RULE_ID, "A-01")


def test_fail_closed_never_lowers() -> None:
    for outcome, expect in [
        (Outcome.ALLOW, Outcome.HOLD),
        (Outcome.HOLD, Outcome.HOLD),
        (Outcome.DENY, Outcome.DENY),
    ]:
        d = Decision(outcome=outcome, rule_ids=("A-01",), policy_version="v1")
        f = fail_closed(d, "X-00")
        assert f.outcome is expect
        assert f.rule_ids == ("A-01", "X-00")
        assert f.policy_version == "v1"


def test_fail_closed_is_idempotent_on_rule_id() -> None:
    d = Decision(outcome=Outcome.ALLOW, rule_ids=(), policy_version="v1")
    assert fail_closed(fail_closed(d, "X-00"), "X-00").rule_ids == ("X-00",)


def test_decide_is_pure_and_deterministic(v1: Policy) -> None:
    a = decide(payment_in(), [sig("secrecy", 0.7)], account_context(), v1)
    b = decide(payment_in(), [sig("secrecy", 0.7)], account_context(), v1)
    assert a == b


def test_policy_with_only_allow_rule_still_holds_when_it_does_not_fire() -> None:
    pol = load_policy(FIXTURES / "allow_only.yaml")
    d = decide(payment_in(), [], account_context(), pol)
    assert d.outcome is Outcome.ALLOW
