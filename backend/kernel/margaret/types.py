"""Margaret boundary types and the two pure persuasion functions.

`MargaretTurn` carries text, a float and an optional `DraftPayment`. It has no field typed
as a kernel Event, Decision or State (asserted in tests/unit/test_boundary.py).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from pydantic import Field, PositiveInt

from kernel.margaret._cues import Hit
from kernel.models import Rail, StrictModel

SAFE_REPLY = "Let me think about that and call my daughter."

# Persuasion weights, one table. Lead amendment 4: three to four attacker turns combining
# warmth with fear or authority must cross DRAFT_THRESHOLD; pure urgency must take 6+ turns.
# Only one increment per kind per turn; the whole turn is capped at MAX_STEP (persona rule:
# "never jumps more than 0.25 in a single turn").
WEIGHTS: dict[str, float] = {
    "warmth": 0.15,
    "threat": 0.15,
    "authority": 0.10,
    "urgency": 0.05,
    "secrecy": 0.05,
}
MAX_STEP = 0.25
DECAY = 0.02
DRAFT_THRESHOLD = 0.75


class DraftPayment(StrictModel):
    amount_cents: PositiveInt
    payee_name: str = Field(min_length=1, max_length=80)
    rail: Rail


class MargaretTurn(StrictModel):
    reply: str
    persuasion: float = Field(ge=0.0, le=1.0)
    draft_payment: DraftPayment | None = None


class Margaret(Protocol):
    name: str
    is_mock: bool

    def reply(
        self, history: Sequence[EvidenceLike], player_text: str, persuasion: float
    ) -> MargaretTurn:
        """One persona turn. Must never raise; failures return SAFE_REPLY with persuasion
        unchanged and no draft."""
        ...


class EvidenceLike(Protocol):
    """Structural view of `kernel.llm.types.EvidenceItem` (id, speaker, text)."""

    @property
    def id(self) -> str: ...
    @property
    def speaker(self) -> str: ...
    @property
    def text(self) -> str: ...


def clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def update_persuasion(current: float, hits: Sequence[Hit]) -> float:
    """Pure. One increment per cue kind per turn, turn total capped at MAX_STEP, clamped to
    [0, 1]. A turn with no weighted cues decays by DECAY."""
    current = round(clamp01(current), 4)
    kinds = {h.kind for h in hits if h.kind in WEIGHTS}
    if not kinds:
        return round(clamp01(current - DECAY), 4)
    step = min(MAX_STEP, sum(WEIGHTS[k] for k in kinds))
    return round(clamp01(current + step), 4)


# ---- amount parsing --------------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_SCALES = {"hundred": 100, "thousand": 1_000, "grand": 1_000, "k": 1_000}
_NUM_WORD = r"(?:" + "|".join(list(_UNITS) + list(_SCALES)) + r")"
_WORD_AMOUNT = re.compile(
    rf"\b((?:{_NUM_WORD}(?:[\s-]+(?:and[\s-]+)?)?)+)(?:\s*(?:dollars|bucks))?\b", re.IGNORECASE
)
_DOLLAR_AMOUNT = re.compile(
    r"(?:\$\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?)"
    r"|(?:\b(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*(?:k\b|dollars\b|bucks\b|USD\b))",
    re.IGNORECASE,
)


def _words_to_int(phrase: str) -> int | None:
    total = 0
    group = 0
    seen_scale = False
    tokens = [t for t in re.split(r"[\s-]+", phrase.strip().lower()) if t and t != "and"]
    if not tokens:
        return None
    for tok in tokens:
        if tok in _UNITS:
            group += _UNITS[tok]
        elif tok in _SCALES:
            seen_scale = True
            if tok == "hundred":
                group = (group or 1) * 100
            else:
                total += (group or 1) * _SCALES[tok]
                group = 0
        else:
            return None
    value = total + group
    return value if seen_scale else None


def parse_amount_cents(text: str) -> int | None:
    """First dollar amount in `text` as cents, or None. Accepts `$1,500`, `$1500.50`,
    `1500 dollars`, `2k`, `fifteen hundred`, `two thousand dollars`."""
    m = _DOLLAR_AMOUNT.search(text)
    if m:
        whole = (m.group(1) or m.group(3) or "").replace(",", "")
        frac = m.group(2) or m.group(4) or "0"
        is_k = bool(m.group(3)) and m.group(0).strip().lower().endswith("k")
        if is_k:
            cents = int(round(float(f"{whole}.{frac}") * 1000)) * 100
        else:
            cents = int(whole) * 100 + int(frac.ljust(2, "0"))
        return cents if cents > 0 else None
    for wm in _WORD_AMOUNT.finditer(text):
        # A scale word (hundred/thousand) is required by _words_to_int; "dollars" is optional.
        value = _words_to_int(wm.group(1))
        if value is not None and value > 0:
            return value * 100
    return None


# ---- rail and payee ----------------------------------------------------------------------

_RAIL_WORDS: tuple[tuple[re.Pattern[str], Rail], ...] = (
    (re.compile(r"\bwire(?:d|s|ing)?\b|\bwire transfer\b", re.IGNORECASE), Rail.WIRE),
    (re.compile(r"\bzelle\b", re.IGNORECASE), Rail.ZELLE),
    (re.compile(r"\bgift ?cards?\b|\bprepaid\b|\bapple cards?\b|\bgoogle play\b", re.IGNORECASE),
     Rail.CARD),
)  # fmt: skip


def infer_rail(text: str) -> Rail:
    for pattern, rail in _RAIL_WORDS:
        if pattern.search(text):
            return rail
    return Rail.ACH


_NAME = r"([A-Z][\w'&.-]*(?:\s+(?:(?:of|the|and|for)\s+)?[A-Z][\w'&.-]*)*)"
_PAYEE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpayable to\s+" + _NAME),
    re.compile(r"\b(?:to|for)\s+(?:the\s+)?" + _NAME),
    re.compile(r"\b(?:from|with|at)\s+(?:the\s+)?" + _NAME),
    re.compile(r"\b(?:this is|I am|I'm)\s+" + _NAME),
)
_ORG_WORDS = re.compile(
    r"\b(IRS|Social Security(?: Administration)?|Medicare|Treasury|FBI|Fraud Department)\b",
    re.IGNORECASE,
)
_STOP_NAMES = {"i", "margaret", "priya", "ms", "mrs", "mr", "dear"}
FALLBACK_PAYEE = "the caller"


def infer_payee(text: str) -> str:
    """Payee from "payable to X", "to X", the caller's claimed organization, else FALLBACK."""
    for pattern in _PAYEE_PATTERNS:
        for m in pattern.finditer(text):
            name = m.group(1).strip(" .,;:!?'\"")
            first = name.split()[0].lower() if name else ""
            if name and first not in _STOP_NAMES and len(name) <= 80:
                return name
    om = _ORG_WORDS.search(text)
    if om:
        return om.group(1)
    return FALLBACK_PAYEE


def extract_draft(text: str, persuasion: float) -> DraftPayment | None:
    """Pure. None unless persuasion > DRAFT_THRESHOLD and `text` names a dollar amount."""
    if persuasion <= DRAFT_THRESHOLD:
        return None
    cents = parse_amount_cents(text)
    if cents is None:
        return None
    return DraftPayment(amount_cents=cents, payee_name=infer_payee(text), rail=infer_rail(text))
