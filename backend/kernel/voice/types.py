"""Voice boundary types. A Transcript carries text and provenance, never a speaker claim."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

INAUDIBLE = "[inaudible]"


class Transcript(BaseModel):
    """What STT produced. There is deliberately no speaker, identity or voice-match field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str
    is_mock: bool
    duration_s: float | None = None


class TTS(Protocol):
    name: str
    is_mock: bool

    def cache_key(self, text: str, voice_id: str) -> str:
        """Cache key this provider would use for the line (lets callers check for a hit)."""
        ...

    def synthesize(self, text: str, voice_id: str) -> Path | None:
        """Return the cached WAV path for `text` in `voice_id`, or None if synthesis failed.
        Never raises; the caller sends `audio_url=None` on None."""
        ...


class STT(Protocol):
    name: str
    is_mock: bool

    def transcribe(self, audio: bytes, mime: str, *, hint: str | None = None) -> Transcript:
        """Return a Transcript for the clip. Never raises; errors become INAUDIBLE, is_mock=True."""
        ...
