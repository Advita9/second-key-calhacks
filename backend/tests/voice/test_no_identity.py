"""Voice is evidence, not identity. Guard against anyone adding a speaker claim later."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

import kernel.voice as voice
from kernel.voice.mock import MockSTT
from kernel.voice.types import Transcript

FORBIDDEN = {
    "speaker",
    "speaker_id",
    "identity",
    "identified",
    "voice_match",
    "voiceprint",
    "match_score",
    "verified",
    "authenticated",
    "customer_id",
}


def test_transcript_has_no_identity_field() -> None:
    fields = set(Transcript.model_fields)
    assert fields == {"text", "provider", "is_mock", "duration_s"}
    assert not (fields & FORBIDDEN)


def test_transcript_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Transcript(text="x", provider="mock", is_mock=True, speaker="margaret")  # type: ignore[call-arg]


def test_module_docstring_states_the_rule() -> None:
    assert voice.__doc__ is not None
    assert voice.__doc__.startswith(
        "Voice is evidence, not identity. Nothing here identifies a speaker."
    )


def test_no_identity_words_in_voice_source() -> None:
    root = Path(voice.__file__).parent
    pat = re.compile(r"\b(speaker[_ ]?id|voiceprint|voice[_ ]match|identify the speaker)\b", re.I)
    for f in root.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not pat.search(src), f"{f.name} mentions speaker identification"


def test_mock_stt_hint_or_inaudible() -> None:
    stt = MockSTT()
    assert stt.transcribe(b"", "audio/webm").text == "[inaudible]"
    t = stt.transcribe(b"", "audio/webm", hint="  wire it today ")
    assert t.text == "wire it today" and t.is_mock is True and t.provider == "mock"
