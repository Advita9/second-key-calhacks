"""Cartesia clients over plain httpx. Sonic TTS (`POST /tts/bytes`) and Ink STT (`POST /stt`).

Facts from docs/research/cartesia.md: header `Cartesia-Version: 2026-08-14`, REST auth is
`Authorization: Bearer`, TTS model `sonic-3.6`, batch STT model `ink-whisper` which accepts
webm/opus from the browser's MediaRecorder directly. Free tier TTS concurrency is 2, so a
lock serializes TTS calls. Both clients fail closed and never raise to the caller.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import httpx

from kernel.voice.cache import AudioCache, audio_key
from kernel.voice.types import INAUDIBLE, Transcript

log = logging.getLogger("second_key.voice")

CARTESIA_BASE_URL = "https://api.cartesia.ai"
CARTESIA_VERSION = "2026-08-14"
TTS_MODEL_ID = "sonic-3.6"
STT_MODEL = "ink-whisper"
# Stock voice "Michelle" (gentle, reassuring). Chosen by the lead probe; no cloning anywhere.
DEFAULT_VOICE_ID = "d7bf7d75-64b7-4c1e-86c0-79d647366587"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Cartesia-Version": CARTESIA_VERSION}


class CartesiaTTS:
    name = "cartesia"
    is_mock = False

    def __init__(
        self,
        api_key: str,
        cache: AudioCache,
        *,
        voice_default: str = DEFAULT_VOICE_ID,
        model_id: str = TTS_MODEL_ID,
        sample_rate: int = 24000,
        client: httpx.Client | None = None,
        base_url: str = CARTESIA_BASE_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self.cache = cache
        self.voice_default = voice_default
        self.model_id = model_id
        self.sample_rate = sample_rate
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s)
        self._headers = _headers(api_key)
        self._lock = threading.Lock()

    def cache_key(self, text: str, voice_id: str) -> str:
        return audio_key(text, voice_id or self.voice_default)

    def request_body(self, text: str, voice_id: str) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "transcript": text,
            "voice": {"id": voice_id or self.voice_default},
            "language": "en",
            "output_format": {
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": self.sample_rate,
            },
        }

    def synthesize(self, text: str, voice_id: str) -> Path | None:
        voice_id = voice_id or self.voice_default
        key = self.cache_key(text, voice_id)
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        try:
            with self._lock:
                resp = self._client.post(
                    f"{self.base_url}/tts/bytes",
                    headers=self._headers,
                    json=self.request_body(text, voice_id),
                )
            resp.raise_for_status()
            data = resp.content
            if not data.startswith(b"RIFF"):
                raise RuntimeError(f"Cartesia TTS returned non-WAV bytes ({len(data)} bytes)")
            return self.cache.put(key, data)
        except Exception:
            log.exception("CartesiaTTS failed; turn continues without audio")
            return None


class CartesiaSTT:
    name = "cartesia"
    is_mock = False

    def __init__(
        self,
        api_key: str,
        *,
        model: str = STT_MODEL,
        language: str = "en",
        client: httpx.Client | None = None,
        base_url: str = CARTESIA_BASE_URL,
        timeout_s: float = 30.0,
    ) -> None:
        self.model = model
        self.language = language
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s)
        self._headers = _headers(api_key)

    def transcribe(self, audio: bytes, mime: str, *, hint: str | None = None) -> Transcript:
        # `hint` is accepted for interface parity and ignored: the real provider transcribes audio.
        try:
            ext = _ext_for(mime)
            resp = self._client.post(
                f"{self.base_url}/stt",
                headers=self._headers,
                data={"model": self.model, "language": self.language},
                files={"file": (f"clip.{ext}", audio, mime or "application/octet-stream")},
            )
            resp.raise_for_status()
            body = resp.json()
            text = body.get("text")
            if not isinstance(text, str):
                raise RuntimeError("Cartesia STT response has no text field")
            duration = body.get("duration")
            duration_s = float(duration) if isinstance(duration, int | float) else None
            return Transcript(
                text=text.strip() or INAUDIBLE,
                provider=self.name,
                is_mock=False,
                duration_s=duration_s,
            )
        except Exception:
            log.exception("CartesiaSTT failed; returning %s", INAUDIBLE)
            return Transcript(text=INAUDIBLE, provider=self.name, is_mock=True, duration_s=None)


def _ext_for(mime: str) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    return {
        "audio/webm": "webm",
        "video/webm": "webm",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/m4a": "m4a",
        "audio/x-m4a": "m4a",
        "audio/flac": "flac",
    }.get(base, "webm")
