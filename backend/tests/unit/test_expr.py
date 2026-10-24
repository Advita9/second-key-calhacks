"""The policy expression language: every operator, precedence, limits, and a fuzz test."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kernel.policy.expr import (
    MAX_DEPTH,
    MAX_TOKENS,
    EvalError,
    ParseError,
    evaluate,
    free_identifiers,
    parse,
    tokenize,
)

KERNEL_DIR = Path(__file__).resolve().parents[2] / "kernel"

ENV: dict[str, object] = {
    "amount_cents": 1_850_000,
    "baseline_90d_cents": 240_000,
    "rail": "WIRE",
    "currency": "USD",
    "beneficiary.is_new": True,
    "beneficiary.on_mule_list": False,
    "signals.secrecy": 0.9,
    "signals.count": 2,
    "zero": 0,
    "neg": -5,
    "half": 0.5,
    "name": "Bay Roofing",
    "tags": ["a", "b"],
}


def ev(src: str, env: dict[str, object] | None = None) -> object:
    return evaluate(parse(src), ENV if env is None else env)


# one test per operator ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("true", True),
        ("false", False),
        ("1 == 1", True),
        ("1 == 2", False),
        ("1 != 2", True),
        ("1 != 1", False),
        ("1 < 2", True),
        ("2 < 1", False),
        ("2 <= 2", True),
        ("3 <= 2", False),
        ("2 > 1", True),
        ("1 > 2", False),
        ("2 >= 2", True),
        ("1 >= 2", False),
        ("1 + 2", 3),
        ("5 - 7", -2),
        ("3 * 4", 12),
        ("6 / 4", 1.5),
        ("-3", -3),
        ("- -3", 3),
        ("not true", False),
        ("not false", True),
        ("true and false", False),
        ("true and true", True),
        ("false or true", True),
        ("false or false", False),
        ("WIRE in [WIRE, ZELLE]", True),
        ("ACH in [WIRE, ZELLE]", False),
        ("ACH not in [WIRE, ZELLE]", True),
        ("WIRE not in [WIRE, ZELLE]", False),
        ("'x' == \"x\"", True),
        ("1 == 1.0", True),
        ("0.7 >= 0.7", True),
        ("1_500_000 == 1500000", True),
        ("[] == []", True),
        ("[1, 2] == [1, 2]", True),
    ],
)
def test_operator(src: str, expected: object) -> None:
    assert ev(src) == expected


def test_identifiers_resolve_from_env() -> None:
    assert ev("amount_cents") == 1_850_000
    assert ev("beneficiary.is_new") is True
    assert ev("rail == WIRE") is True
    assert ev("rail in [WIRE, ZELLE, CRYPTO]") is True
    assert ev("'a' in tags") is True
    assert ev("amount_cents > 3 * baseline_90d_cents") is True
    assert ev("signals.secrecy >= 0.7 and beneficiary.is_new") is True


# precedence -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("2 * 3 + 1", 7),
        ("10 - 4 - 3", 3),
        ("12 / 2 / 3", 2.0),
        ("-2 * 3", -6),
        ("1 + 2 == 3", True),
        ("1 < 2 == true", None),  # chained comparisons are a ParseError
        ("not 1 == 2", True),  # not binds looser than ==
        ("not true and false", False),  # (not true) and false
        ("true or false and false", True),  # and binds tighter than or
        ("false and false or true", True),
        ("not false or false", True),
        ("1 + 2 in [3]", True),
        ("2 * 3 > 5 and 1 < 2", True),
    ],
)
def test_precedence(src: str, expected: object) -> None:
    if expected is None:
        with pytest.raises(ParseError):
            parse(src)
    else:
        assert ev(src) == expected


def test_short_circuit_still_type_checks_evaluated_side() -> None:
    assert ev("false and 1") is False  # right side never evaluated
    assert ev("true or 1") is True
    with pytest.raises(EvalError):
        ev("true and 1")
    with pytest.raises(EvalError):
        ev("1 or true")


# literals and identifiers -----------------------------------------------------------------


def test_all_caps_bare_identifier_is_string_literal() -> None:
    assert ev("WIRE") == "WIRE"
    assert ev("PG_E2") == "PG_E2"
    assert free_identifiers(parse("rail == WIRE and beneficiary.is_new")) == frozenset(
        {"rail", "beneficiary.is_new"}
    )
    assert free_identifiers(parse("WIRE in [ZELLE, CRYPTO]")) == frozenset()


def test_mixed_case_is_identifier_not_literal() -> None:
    assert free_identifiers(parse("Wire")) == frozenset({"Wire"})
    assert free_identifiers(parse("True")) == frozenset({"True"})


def test_unknown_identifier_raises_eval_error() -> None:
    with pytest.raises(EvalError):
        ev("nope")
    with pytest.raises(EvalError):
        ev("beneficiary.nope == 1")


def test_keywords_cannot_be_identifiers() -> None:
    with pytest.raises(ParseError):
        parse("and")
    with pytest.raises(ParseError):
        parse("in")
    with pytest.raises(ParseError):
        parse("a.and")


# limits and failure modes -----------------------------------------------------------------


def test_depth_bomb_is_parse_error() -> None:
    src = "(" * (MAX_DEPTH + 5) + "1" + ")" * (MAX_DEPTH + 5)
    with pytest.raises(ParseError):
        parse(src)
    src = "-" * (MAX_DEPTH + 5) + "1"
    with pytest.raises(ParseError):
        parse(src)
    src = "[" * (MAX_DEPTH + 5) + "]" * (MAX_DEPTH + 5)
    with pytest.raises(ParseError):
        parse(src)


def test_moderate_depth_is_fine() -> None:
    src = "(" * 20 + "1" + ")" * 20
    assert ev(src) == 1


def test_token_bomb_is_parse_error() -> None:
    src = " + ".join(["1"] * (MAX_TOKENS + 10))
    with pytest.raises(ParseError):
        tokenize(src)


def test_division_by_zero_is_eval_error() -> None:
    with pytest.raises(EvalError):
        ev("1 / 0")
    with pytest.raises(EvalError):
        ev("1 / zero")
    with pytest.raises(EvalError):
        ev("1 / 0.0")


@pytest.mark.parametrize(
    "src",
    [
        "",
        "   ",
        "1 +",
        "+ 1",
        "(1",
        "1)",
        "[1, 2",
        "1 2",
        "1 == == 2",
        "'unterminated",
        "1 @ 2",
        "a..b",
        "a.",
        ".a",
        "1.",
        "1..2",
        "1 < 2 < 3",
        "in [1]",
        "not",
        "[1,, 2]",
        "1 not 2",
        "x = 1",
        "x => 1",
        "a = = b",
    ],
)
def test_syntax_errors(src: str) -> None:
    with pytest.raises(ParseError):
        parse(src)


@pytest.mark.parametrize(
    "src",
    [
        "1 < 'a'",
        "'a' + 1",
        "'a' + 'b'",
        "true + 1",
        "true < false",
        "1 in 2",
        "1 in 'abc'",
        "'a' in name",
        "-'a'",
        "-true",
        "not 1",
        "not 'x'",
        "[1] < [2]",
        "1 * 'a'",
        "half / zero",
    ],
)
def test_type_errors_are_eval_errors(src: str) -> None:
    with pytest.raises(EvalError):
        ev(src)


def test_bool_is_not_a_number() -> None:
    with pytest.raises(EvalError):
        ev("true + 0 == 1")
    assert ev("true == 1") is False
    assert ev("false == 0") is False


def test_huge_numbers_do_not_crash() -> None:
    big = "9" * 400
    assert isinstance(ev(f"{big} * {big}"), int)
    with pytest.raises(EvalError):
        ev(f"{big} / 3")  # int too large for float -> EvalError, never OverflowError


def test_parse_is_pure_and_repeatable() -> None:
    assert parse("1 + a") == parse("1 + a")


# fuzz ---------------------------------------------------------------------------------------

_ALPHABET = "abcxyzWIREZ._ 0123456789+-*/<>=!()[],'\"andornotitrue"


@given(st.text(alphabet=_ALPHABET, max_size=200))
def test_fuzz_only_parse_or_eval_errors(src: str) -> None:
    try:
        node = parse(src)
    except ParseError:
        return
    try:
        evaluate(node, ENV)
    except EvalError:
        return


@given(st.text(max_size=120))
def test_fuzz_unicode_only_parse_or_eval_errors(src: str) -> None:
    try:
        node = parse(src)
    except ParseError:
        return
    try:
        evaluate(node, ENV)
    except EvalError:
        return


@given(
    st.recursive(
        st.sampled_from(["1", "2.5", "0", "true", "false", "WIRE", "'s'", "amount_cents", "half"]),
        lambda inner: st.one_of(
            st.tuples(
                inner,
                st.sampled_from(
                    [
                        "+",
                        "-",
                        "*",
                        "/",
                        "==",
                        "!=",
                        "<",
                        "<=",
                        ">",
                        ">=",
                        "and",
                        "or",
                        "in",
                        "not in",
                    ]
                ),
                inner,
            ).map(lambda t: f"({t[0]} {t[1]} {t[2]})"),
            inner.map(lambda s: f"(not {s})"),
            inner.map(lambda s: f"(-{s})"),
            st.lists(inner, max_size=3).map(lambda xs: "[" + ", ".join(xs) + "]"),
        ),
        max_leaves=40,
    )
)
def test_fuzz_structured_expressions(src: str) -> None:
    try:
        node = parse(src)
    except ParseError:
        return
    try:
        out = evaluate(node, ENV)
    except EvalError:
        return
    assert isinstance(out, bool | int | float | str | list)


# no eval/exec anywhere in the kernel ----------------------------------------------------------


def test_no_eval_or_exec_in_kernel() -> None:
    # builtins eval/exec/compile; `re.compile(` is the regex engine and is allowed
    pat = re.compile(r"(?<![\w.])(eval|exec|compile)\s*\(")
    hits = [
        f"{p.relative_to(KERNEL_DIR)}:{i}"
        for p in KERNEL_DIR.rglob("*.py")
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if pat.search(line) and not line.lstrip().startswith("#")
    ]
    assert hits == []
