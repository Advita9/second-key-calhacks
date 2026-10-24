"""Private persuasion-cue scanner for MockMargaret.

TODO(T5/T6 merge): switch to the shared `kernel.llm.heuristics.scan` once it lands. This
module keeps the same `Hit(kind, span, score)` shape so the swap is a one-line import change.
Pure: regex only, no I/O.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from pydantic import Field

from kernel.models import StrictModel

Kind = Literal[
    "warmth",
    "threat",
    "authority",
    "urgency",
    "secrecy",
    "payment_method",
    "new_relationship",
]
KINDS: tuple[str, ...] = tuple(get_args(Kind))


class Hit(StrictModel):
    kind: Kind
    span: str
    score: float = Field(ge=0.0, le=1.0)


def _rx(*words: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


PATTERNS: dict[Kind, tuple[tuple[re.Pattern[str], float], ...]] = {
    "warmth": (
        (
            _rx(
                "darling",
                "my dear",
                "i love you",
                "angel",
                "sweetheart",
                "you sound just like",
                "grandma",
                "grandmother",
                "nana",
            ),
            0.8,
        ),
    ),
    "threat": (
        (
            _rx(
                "warrant",
                "arrest(?:ed)?",
                "jail",
                "prison",
                "shut off",
                "frozen",
                "freeze",
                "lose everything",
                "lawsuit",
                "police",
            ),
            0.9,
        ),
    ),
    "authority": (
        (
            _rx(
                "irs",
                "social security",
                "medicare",
                "fraud department",
                "officer",
                "agent",
                "treasury",
                "your bank",
                "federal",
            ),
            0.8,
        ),
    ),
    "urgency": (
        (
            _rx(
                "today",
                "right now",
                "within the hour",
                "immediately",
                "before 5",
                "right away",
                "hurry",
                "no time",
                "last chance",
            ),
            0.7,
        ),
    ),
    "secrecy": (
        (
            re.compile(
                r"\b(?:do not tell|don'?t tell|between us|our secret|keep this quiet|"
                r"don'?t mention|confidential)\b",
                re.IGNORECASE,
            ),
            0.9,
        ),
    ),
    "payment_method": ((_rx("wire", "gift cards?", "prepaid", "bitcoin", "crypto", "zelle"), 0.7),),
    "new_relationship": ((_rx("we just met", "never spoken", "first time"), 0.5),),
}


def scan(text: str) -> tuple[Hit, ...]:
    """Every pattern match, in source order. Span is the exact matched substring."""
    out: list[Hit] = []
    for kind, rules in PATTERNS.items():
        for pattern, score in rules:
            for m in pattern.finditer(text):
                out.append(Hit(kind=kind, span=text[m.start() : m.end()], score=score))
    return tuple(out)
