"""MockMargaret: scripted persona driven by the cue scanner and the fixture fallback lines.

Labelled MOCK in the UI footer. Deterministic: the same history and text give the same turn.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from pathlib import Path

from kernel.margaret._cues import scan
from kernel.margaret.persona import band_index, load_fallback_lines
from kernel.margaret.types import (
    DRAFT_THRESHOLD,
    SAFE_REPLY,
    EvidenceLike,
    MargaretTurn,
    extract_draft,
    update_persuasion,
)

log = logging.getLogger("second_key.margaret")

ASK_AMOUNT = "All right, dear, I will do it. How much do you need me to send, and to whom?"
RECENT_PLAYER_TURNS = 4
_LONG_DIGITS = re.compile(r"\d{8,}")


def is_margaret(speaker: str) -> bool:
    return speaker.strip().lower() == "margaret"


def player_turns(history: Sequence[EvidenceLike]) -> list[str]:
    return [item.text for item in history if not is_margaret(item.speaker)]


class MockMargaret:
    name = "mock"
    is_mock = True

    def __init__(self, persona_path: Path | None = None) -> None:
        self._bands = load_fallback_lines(persona_path)
        for band in self._bands:
            for line in band:
                if _LONG_DIGITS.search(line) or "—" in line:
                    raise ValueError("fallback line contains a long digit run or an em dash")

    def reply(
        self, history: Sequence[EvidenceLike], player_text: str, persuasion: float
    ) -> MargaretTurn:
        try:
            return self._reply(history, player_text, persuasion)
        except Exception:  # fail closed: never raise into the room loop
            log.exception("margaret.mock.failed")
            return MargaretTurn(reply=SAFE_REPLY, persuasion=persuasion, draft_payment=None)

    def _reply(
        self, history: Sequence[EvidenceLike], player_text: str, persuasion: float
    ) -> MargaretTurn:
        hits = scan(player_text)
        new = update_persuasion(persuasion, hits)
        turn_count = len(player_turns(history))
        draft = None
        if new > DRAFT_THRESHOLD:
            recent = player_turns(history)[-RECENT_PLAYER_TURNS:] + [player_text]
            draft = extract_draft("\n".join(recent), new)
        band = band_index(new)
        lines = self._bands[band]
        reply = lines[turn_count % len(lines)]
        if new > DRAFT_THRESHOLD and draft is None:
            reply = ASK_AMOUNT
        log.info(
            "margaret.turn mode=mock band=%d persuasion=%.2f cues=%s draft=%s",
            band,
            new,
            sorted({h.kind for h in hits}),
            draft is not None,
        )
        return MargaretTurn(reply=reply, persuasion=new, draft_payment=draft)
