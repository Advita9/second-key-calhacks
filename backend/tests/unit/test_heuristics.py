"""Regex scanner shared by MockExtractor and MockMargaret. Pure, case-insensitive, exact spans."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kernel.llm.heuristics import PATTERNS, Hit, negated, scan
from kernel.llm.types import SIGNAL_KINDS


def test_patterns_cover_every_signal_kind_plus_warmth() -> None:
    assert set(PATTERNS) == {*SIGNAL_KINDS, "warmth"}
    for kind, table in PATTERNS.items():
        assert table, kind
        for _pat, score in table:
            assert 0.0 < score <= 1.0


def test_span_is_exact_substring_and_case_insensitive() -> None:
    text = "DO NOT TELL YOUR DAUGHTER about this."
    hits = scan(text)
    secrecy = [h for h in hits if h.kind == "secrecy"]
    assert secrecy, hits
    for h in hits:
        assert h.span in text
        assert text.find(h.span) == text.lower().find(h.span.lower())
    assert secrecy[0].span == "DO NOT TELL YOUR DAUGHTER"


@pytest.mark.parametrize(
    ("text", "kind", "min_score"),
    [
        ("Do not tell your bank or your daughter", "secrecy", 0.7),
        ("That is why we keep us between us for now.", "secrecy", 0.7),
        ("Remember, our secret until I land.", "secrecy", 0.7),
        ("This is Agent Daniels with the IRS.", "authority", 0.7),
        ("or local police will be dispatched", "threat", 0.7),
        ("You must do it before the end of the business day", "urgency", 0.8),
        ("Buy three gift cards at Walgreens", "payment_method", 0.8),
        ("Good morning my darling Margaret.", "warmth", 0.6),
        ("we updated our bank details last week", "new_relationship", 0.5),
    ],
)
def test_table_examples(text: str, kind: str, min_score: float) -> None:
    hits = [h for h in scan(text) if h.kind == kind]
    assert hits, f"no {kind} hit in {text!r}"
    assert max(h.score for h in hits) >= min_score


def test_no_hurry_is_not_urgency() -> None:
    assert not [
        h
        for h in scan("Great. No hurry, any time before the weekend works.")
        if h.kind == "urgency"
    ]


def test_benign_text_yields_nothing() -> None:
    assert scan("The crew starts Monday on the garage roof.") == ()
    assert scan("") == ()


def test_hits_are_ordered_and_frozen() -> None:
    hits = scan("Wire it today. Do not tell your daughter.")
    starts = ["Wire it today. Do not tell your daughter.".find(h.span) for h in hits]
    assert starts == sorted(starts)
    with pytest.raises(ValidationError):
        hits[0].span = "x"  # type: ignore[misc]
    assert isinstance(hits[0], Hit)


def test_negated_deadline_is_not_urgency() -> None:
    text = "There is no deadline this week, take your time."
    assert not [h for h in scan(text) if h.kind == "urgency"]
    assert negated(text, text.find("deadline"))


def test_cancelled_plan_is_not_a_threat() -> None:
    text = "We refunded you four hundred for the cancelled plan but our technician erred."
    assert not [h for h in scan(text) if h.kind == "threat"]


@pytest.mark.parametrize(
    "text",
    [
        "Your account will be cancelled tonight.",
        "We will cancel your benefits if you hang up.",
        "Your social security number has been suspended.",
    ],
)
def test_shutoff_phrasing_is_still_a_threat(text: str) -> None:
    assert [h for h in scan(text) if h.kind == "threat"]


def test_negation_window_is_three_words_and_same_sentence() -> None:
    assert not [h for h in scan("I have not seen any deadline") if h.kind == "urgency"]
    assert [h for h in scan("No. The deadline is today.") if h.kind == "urgency"]
    assert [
        h for h in scan("Not that it matters much to me, deadline is now") if h.kind == "urgency"
    ]
    # negation inside the span itself (secrecy starts with "do not") is not self-cancelling
    assert [h for h in scan("Do not tell your daughter.") if h.kind == "secrecy"]
