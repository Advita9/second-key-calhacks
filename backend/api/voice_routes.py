"""Voice routes. Mount with `app.include_router(voice_router)` in api/main.py.

GET  /audio/{key}.wav         serves a cached render (key = 64 hex chars).
POST /rooms/{room}/stt        multipart `audio` (+ optional `text` hint) -> transcript JSON.

The transcript is evidence text for the turn. It carries provider and is_mock so the UI can
label MOCK output. It never carries a speaker claim.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kernel.voice.cache import AudioCache, default_cache_root, is_audio_key
from kernel.voice.factory import make_stt
from kernel.voice.types import STT

log = logging.getLogger("second_key.api.voice")

MAX_AUDIO_BYTES = 10 * 1024 * 1024

router = APIRouter(tags=["voice"])


class SttResponse(BaseModel):
    transcript: str
    provider: str
    is_mock: bool
    duration_s: float | None = None


_stt: STT | None = None
_cache: AudioCache | None = None


def get_stt() -> STT:
    global _stt
    if _stt is None:
        _stt = make_stt()
    return _stt


def set_stt(stt: STT | None) -> None:
    """Inject a provider (tests, or main.py after loading .env). None resets to env."""
    global _stt
    _stt = stt


def get_cache() -> AudioCache:
    global _cache
    if _cache is None:
        _cache = AudioCache(default_cache_root())
    return _cache


def reset_providers() -> None:
    """Tests and env changes: drop the cached provider instances."""
    global _stt, _cache
    _stt = None
    _cache = None


@router.get("/audio/{key}.wav")
def get_audio(key: str) -> FileResponse:
    if not is_audio_key(key):
        raise HTTPException(status_code=404, detail="no such audio")
    path = get_cache().get(key)
    if path is None:
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(path, media_type="audio/wav", filename=f"{key}.wav")


@router.post("/rooms/{room}/stt")
async def stt(
    room: str,
    audio: Annotated[UploadFile, File()],
    text: Annotated[str | None, Form()] = None,
) -> SttResponse:
    data = await audio.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio clip too large")
    if not data:
        raise HTTPException(status_code=400, detail="empty audio clip")
    mime = audio.content_type or "application/octet-stream"
    provider = get_stt()
    t = provider.transcribe(data, mime, hint=text)
    log.info(
        "stt room=%s provider=%s mock=%s bytes=%d chars=%d",
        room,
        t.provider,
        t.is_mock,
        len(data),
        len(t.text),
    )
    return SttResponse(
        transcript=t.text, provider=t.provider, is_mock=t.is_mock, duration_s=t.duration_s
    )
