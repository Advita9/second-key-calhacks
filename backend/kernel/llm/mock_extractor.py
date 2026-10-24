"""MockExtractor: deterministic heuristic signals, same interface as ClaudeExtractor.

Scans only lines spoken by someone other than Margaret. Every Signal cites the real evidence id
and the exact matched substring, so it is indistinguishable in shape from a grounded model
answer. It reads nothing but the conversation and the payment. Labeled MOCK in /health.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from kernel.llm.heuristics import scan
from kernel.llm.types import SIGNAL_KINDS, EvidenceItem, ExtractorResult, Signal
from kernel.models import PaymentIn

log = logging.getLogger("second_key.llm.mock")

CUSTOMER_SPEAKER = "margaret"


def is_customer(speaker: str) -> bool:
    return speaker.strip().lower() == CUSTOMER_SPEAKER


class MockExtractor:
    def __init__(self, *, max_signals: int = 12) -> None:
        self.max_signals = max_signals

    def extract(self, conversation: Sequence[EvidenceItem], payment: PaymentIn) -> ExtractorResult:
        signals: list[Signal] = []
        seen: set[tuple[str, str, str]] = set()
        scanned = 0
        for item in conversation:
            if is_customer(item.speaker):
                continue
            scanned += 1
            for hit in scan(item.text):
                if hit.kind not in SIGNAL_KINDS:
                    continue  # warmth is for Margaret's persuasion, not a policy signal
                key = (hit.kind, item.id, hit.span)
                if key in seen:
                    continue
                seen.add(key)
                signals.append(
                    Signal.model_validate(
                        {
                            "kind": hit.kind,
                            "score": hit.score,
                            "source_id": item.id,
                            "evidence_span": hit.span,
                        }
                    )
                )
        signals.sort(key=lambda s: s.score, reverse=True)
        kept = tuple(signals[: self.max_signals])
        kinds = sorted({s.kind for s in kept})
        summary = (
            f"MOCK heuristic scan: {len(kept)} signal(s) across {scanned} counterparty line(s)"
            + (f"; kinds: {', '.join(kinds)}" if kinds else "")
        )
        log.info(
            "extractor.mock",
            extra={"n_items": len(conversation), "n_signals": len(kept), "kinds": kinds},
        )
        return ExtractorResult(signals=kept, summary=summary)
