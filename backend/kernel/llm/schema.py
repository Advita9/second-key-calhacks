"""Per-request output model and the defensive sanitizer.

`build_output_model` makes `source_id` a `Literal` of exactly this request's evidence ids, so a
model that invents an id fails validation before anything else happens. `sanitize` is the last
line of defence: it takes an arbitrary mapping and returns an `ExtractorResult` containing only
signals whose span is a verbatim substring of the cited item. It never raises.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from kernel.llm.types import (
    SIGNAL_KINDS,
    EvidenceItem,
    ExtractorError,
    ExtractorResult,
    Signal,
    SignalKind,
)

MAX_SUMMARY_CHARS = 500


class _OutBase(BaseModel):
    """Non-strict on purpose: the API returns JSON, where 1 and 1.0 are both fine. Extra keys
    are forbidden so a drifted schema is a loud failure (X-00), not a silent one."""

    model_config = ConfigDict(extra="forbid")


def build_output_model(evidence_ids: Sequence[str]) -> type[BaseModel]:
    ids = tuple(dict.fromkeys(evidence_ids))  # dedupe, keep order
    if not ids:
        raise ExtractorError("no evidence ids: nothing for the model to cite")
    source_literal = Literal[ids]  # type: ignore[valid-type]
    signal_model = create_model(
        "SignalOut",
        __base__=_OutBase,
        kind=(SignalKind, Field(description="tactic category")),
        score=(float, Field(ge=0.0, le=1.0, description="confidence 0 to 1")),
        source_id=(source_literal, Field(description="id of the evidence item cited")),
        evidence_span=(
            str,
            Field(min_length=1, description="verbatim substring of that evidence item's text"),
        ),
    )
    return create_model(
        "ExtractorOutput",
        __base__=_OutBase,
        signals=(list[signal_model], Field(description="zero or more grounded signals")),
        summary=(str, Field(description="one sentence")),
    )


def _clamp_score(raw: object) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    if math.isnan(value) or math.isinf(value):
        return None
    return min(1.0, max(0.0, value))


def _one(item: object, by_id: Mapping[str, EvidenceItem]) -> Signal | None:
    if not isinstance(item, Mapping):
        return None
    kind = item.get("kind")
    source_id = item.get("source_id")
    span = item.get("evidence_span")
    score = _clamp_score(item.get("score"))
    if not isinstance(kind, str) or kind not in SIGNAL_KINDS:
        return None
    if not isinstance(source_id, str) or source_id not in by_id:
        return None
    if not isinstance(span, str) or not span or span not in by_id[source_id].text:
        return None
    if score is None:
        return None
    try:
        return Signal.model_validate(
            {"kind": kind, "score": score, "source_id": source_id, "evidence_span": span}
        )
    except Exception:  # noqa: BLE001  defensive: never let garbage escape as an exception
        return None


def sanitize(
    raw: Mapping[str, object],
    evidence: Sequence[EvidenceItem],
    *,
    max_signals: int = 12,
) -> ExtractorResult:
    """Keep only signals that cite a real item by id with a verbatim span. Never raises."""
    try:
        by_id = {e.id: e for e in evidence}
        signals: list[Signal] = []
        raw_signals: Any = raw.get("signals") if isinstance(raw, Mapping) else None
        if isinstance(raw_signals, list | tuple):
            for item in raw_signals:
                sig = _one(item, by_id)
                if sig is not None:
                    signals.append(sig)
                if len(signals) >= max_signals:
                    break
        raw_summary = raw.get("summary") if isinstance(raw, Mapping) else None
        summary = raw_summary[:MAX_SUMMARY_CHARS] if isinstance(raw_summary, str) else ""
        return ExtractorResult(signals=tuple(signals), summary=summary)
    except Exception:  # noqa: BLE001
        return ExtractorResult()
