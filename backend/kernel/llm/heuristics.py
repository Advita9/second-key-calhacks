"""Pure regex scanner for coaching tactics. Shared by MockExtractor and MockMargaret.

Case-insensitive. Each `Hit.span` is the exact matched substring of the input, so a Signal built
from it always satisfies the "evidence_span is a substring" rule. `warmth` exists for Margaret's
persuasion model only; it is not a policy signal kind and MockExtractor filters it out.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal[
    "urgency",
    "secrecy",
    "authority",
    "payment_method",
    "new_relationship",
    "threat",
    "warmth",
]


class Hit(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")
    kind: Kind
    span: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)


def _p(*parts: str) -> re.Pattern[str]:
    """Join fragments (so long alternations fit the line limit), compile case-insensitive."""
    return re.compile("".join(parts), re.IGNORECASE)


_WHO = (
    r"(your |the |my )?(bank|banker|teller|daughter|son|family|anyone|anybody|wife|husband"
    r"|children|kids|friends|grandchildren|nurse|caregiver)"
)

PATTERNS: dict[Kind, tuple[tuple[re.Pattern[str], float], ...]] = {
    "urgency": (
        (_p(r"before the end of the (business )?day"), 0.9),
        (_p(r"\b(right now|immediately|right away|this instant|this minute)\b"), 0.8),
        (_p(r"\bwithin (the (next )?hour|\d+ (minutes|hours))\b"), 0.8),
        (_p(r"\b(time is running out|last chance|final notice|deadline)\b"), 0.8),
        (_p(r"\b(urgent(ly)?|emergency)\b"), 0.7),
        (_p(r"(?<!\bno )\b(hurry|rush)\b"), 0.6),
        (_p(r"\b(today|tonight)\b"), 0.6),
        (_p(r"\bas soon as possible\b|\basap\b"), 0.5),
    ),
    "secrecy": (
        (
            _p(
                r"\b(do not|don'?t|never|can'?t|cannot) ",
                r"(tell|call|contact|involve|mention (this|it) to) ",
                _WHO,
            ),
            0.9,
        ),
        (_p(r"\bif (the bank|they|anyone|the teller) asks?,? (say|tell them|just say)\b"), 0.9),
        (
            _p(
                r"\b(keep|stay|remain) (this|it|us|things|everything) ",
                r"(between us|secret|quiet|private|confidential)\b",
            ),
            0.8,
        ),
        (
            _p(
                r"\b(tell no ?one|not a word to|keep it to yourself|don'?t say anything",
                r"|do not say anything|don'?t mention|do not mention)\b",
            ),
            0.8,
        ),
        (_p(r"\bour (little )?secret\b"), 0.8),
        (_p(r"\b(between us|between you and me|just between us)\b"), 0.7),
        (_p(r"\b(part of|in on|under) the investigation\b"), 0.7),
        (_p(r"\bno one (else )?(needs|has) to know\b"), 0.8),
    ),
    "authority": (
        (
            _p(
                r"\b(IRS|internal revenue service|social security( administration)?|medicare",
                r"|medicaid|FBI|DEA|the treasury|federal (agent|marshal|reserve|trade commission)",
                r"|department of justice|homeland security|sheriff'?s? (office|department))\b",
            ),
            0.8,
        ),
        (_p(r"\b(agent|officer|detective|investigator|inspector|marshal) [a-z]+\b"), 0.7),
        (_p(r"\b(fraud|security|investigations?) (department|team|division|unit)\b"), 0.7),
        (
            _p(
                r"\b(microsoft|apple|amazon|geek squad|norton|mcafee|windows) ",
                r"(support|security|tech(nical)? support|team)\b",
            ),
            0.7,
        ),
        (
            _p(
                r"\b(this is|calling from|on behalf of|i am with|i'?m with) (the )?",
                r"(bank|your bank|chase|wells fargo|bank of america|citi(bank)?",
                r"|the court|the county|the state)\b",
            ),
            0.7,
        ),
        (_p(r"\b(case|badge|reference|file) (number|id|no\.?)\b"), 0.6),
    ),
    "payment_method": (
        (
            _p(
                r"\b(gift ?cards?|itunes cards?|google play cards?|steam cards?",
                r"|prepaid cards?|vanilla cards?)\b",
            ),
            0.9,
        ),
        (_p(r"\b(bitcoin|crypto(currency)?|btc|ethereum|coinbase|bitcoin atm|crypto atm)\b"), 0.9),
        (_p(r"\b(western union|moneygram|cash app|cashapp|venmo|paypal friends)\b"), 0.7),
        (_p(r"\bwire( transfer| it| the money| the funds)?\b"), 0.6),
        (_p(r"\bzelle\b"), 0.5),
        (
            _p(
                r"\b(cash|cashier'?s check) (in|inside|wrapped|to|via|by) (a|the|an) ",
                r"(box|envelope|magazine|courier|package)\b",
            ),
            0.9,
        ),
    ),
    "new_relationship": (
        (
            _p(
                r"\b(we('ve| have) (just|only) (met|spoken|been talking)|first time (we|you)",
                r"|first (call|contact))\b",
            ),
            0.7,
        ),
        (
            _p(
                r"\b(new (account|number|payee|vendor|bank details|bank account|routing number)",
                r"|updated (our|my|the) (account|bank|payment|banking) ",
                r"(details|information|info|number|numbers)",
                r"|changed (our|my) (bank|account|banking)( details| information)?)\b",
            ),
            0.7,
        ),
        (
            _p(
                r"\b(i'?m|i am|this is) (a |the )?(new|your new) ",
                r"(contractor|agent|rep|representative|nurse|caregiver|caseworker",
                r"|adviser|advisor|manager|contact)\b",
            ),
            0.6,
        ),
        (_p(r"\b(add me|add (him|her|them)) as (a )?(payee|recipient|contact)\b"), 0.6),
    ),
    "threat": (
        (
            _p(
                r"\b(warrant|arrest(ed)?|police|sheriff|jail|prison|deport(ed|ation)?|lawsuit",
                r"|legal action|prosecut(ed|ion)|criminal charges|charges (will be )?filed)\b",
            ),
            0.8,
        ),
        (
            _p(
                r"\b(will be |is |are |gets? |being )?(suspended|frozen|terminated|disconnected",
                r"|shut (off|down)|cut off|seized)\b",
            ),
            0.7,
        ),
        (
            _p(
                r"\b((will|would|is going to|is about to) be cancell?ed",
                r"|cancel(l?ing)? (your|the|all) (account|accounts|benefits|service|card|cards",
                r"|policy|coverage|social security|medicare|pension|warrant))\b",
            ),
            0.7,
        ),
        (
            _p(
                r"\b(or else|face (the )?consequences|held (liable|responsible)",
                r"|you will (lose|be liable|be fined)",
                r"|lose (your|the) (house|home|benefits|account|pension|savings))\b",
            ),
            0.7,
        ),
        (_p(r"\b(if you (hang up|don'?t|do not|refuse)|you have no choice)\b"), 0.6),
    ),
    "warmth": (
        (
            _p(
                r"\b(i love you|love you|miss you|missing you",
                r"|you are my (angel|everything|world|rock)",
                r"|you'?re my (angel|everything|world|rock))\b",
            ),
            0.8,
        ),
        (
            _p(
                r"\b(my (darling|angel|love|dear|sweetheart|queen|sunshine|beautiful)",
                r"|darling|sweetheart|honey|dearest|my dear)\b",
            ),
            0.7,
        ),
        (
            _p(
                r"\b(you'?re|you are) (such )?a (good|kind|wonderful|generous|special|lovely) ",
                r"(woman|person|lady|soul)\b",
            ),
            0.6,
        ),
        (
            _p(
                r"\b(bless you|god bless|thinking of you",
                r"|you remind me of my (mother|grandmother|mom))\b",
            ),
            0.5,
        ),
    ),
}


NEGATION_WORDS: frozenset[str] = frozenset({"no", "not", "never", "without"})
NEGATION_WINDOW = 3
_PUNCT = ".,;:!?\"'()[]"


def negated(text: str, start: int) -> bool:
    """True if a negation word sits within NEGATION_WINDOW words before `start`, in the same
    sentence. "There is no deadline this week" negates "deadline"."""
    before = text[:start].split()
    for token in reversed(before[-NEGATION_WINDOW:]):
        word = token.strip(_PUNCT).lower()
        if word in NEGATION_WORDS:
            return True
        if token[-1:] in ".!?;":
            return False  # sentence boundary
    return False


def scan(text: str) -> tuple[Hit, ...]:
    """Every pattern match in `text`, ordered by position then kind. Pure."""
    found: list[tuple[int, str, Hit]] = []
    for kind, table in PATTERNS.items():
        for pattern, score in table:
            for m in pattern.finditer(text):
                span = text[m.start() : m.end()]
                if not span or negated(text, m.start()):
                    continue
                found.append((m.start(), kind, Hit(kind=kind, span=span, score=score)))
    found.sort(key=lambda t: (t[0], t[1]))
    return tuple(h for _, _, h in found)
