"""Types at the model boundary (I4). Nothing here may import state, db, certs or service.

The model can only produce `Signal`s and text. A `Decision` is produced by the policy engine
from signals; a state transition is produced by the service from a Decision. There is no
constructor path from `ExtractorResult` to any `Event`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol, get_args

from pydantic import Field

from kernel.models import PaymentIn, StrictModel

SignalKind = Literal[
    "urgency", "secrecy", "authority", "payment_method", "new_relationship", "threat"
]
SIGNAL_KINDS: tuple[str, ...] = tuple(get_args(SignalKind))


# Speakers whose lines are context, never attacker speech: the customer, her co-approver, the
# bank, operators, and shared reference material (fixtures/evidence.json, speaker="reference").
COUNTERPARTY_EXCLUDED: frozenset[str] = frozenset({"margaret", "priya", "bank", "ops", "reference"})


def is_counterparty(speaker: str, counterparty_speakers: frozenset[str] | None = None) -> bool:
    """True if this speaker's words count as the other party's tactics.

    With `counterparty_speakers` set, only those speakers count (exact, case-insensitive).
    Otherwise everyone not in COUNTERPARTY_EXCLUDED counts.
    """
    name = speaker.strip().lower()
    if counterparty_speakers is not None:
        return name in {c.strip().lower() for c in counterparty_speakers}
    return name not in COUNTERPARTY_EXCLUDED


class Signal(StrictModel):
    kind: SignalKind
    score: float = Field(ge=0.0, le=1.0)
    source_id: str = Field(min_length=1)
    evidence_span: str


class EvidenceItem(StrictModel):
    id: str = Field(min_length=1)
    speaker: str
    text: str


class ExtractorResult(StrictModel):
    signals: tuple[Signal, ...] = ()
    summary: str = ""


class ExtractorError(Exception):
    """Any failure between the model boundary and a validated ExtractorResult.

    Raised by ClaudeExtractor on API errors, timeouts, refusals, truncation, missing or
    ill-typed parsed output, foreign evidence ids, or a replay-only cache miss. The kernel
    catches it and fails closed (rule X-00). Never carries prompt text or secrets.
    """


class Extractor(Protocol):
    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        """Return validated signals citing evidence ids. Must never raise on bad model output;
        callers still wrap this in try/except and fail closed (X-00)."""
        ...


class NullExtractor:
    """Emits nothing. The policy engine must hold or deny on rules alone."""

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        return ExtractorResult(signals=(), summary="")
