"""Pin the recorded real Cartesia responses so the request shapes stay honest without network."""

from __future__ import annotations

import io
import json
import wave
from typing import Any

import httpx

from kernel.voice.cache import AudioCache, audio_key
from kernel.voice.cartesia import CartesiaTTS


def test_recorded_tts_wav_is_24k_mono_pcm16(recorded_tts_wav: bytes) -> None:
    assert recorded_tts_wav.startswith(b"RIFF") and recorded_tts_wav[8:12] == b"WAVE"
    with wave.open(io.BytesIO(recorded_tts_wav), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() > 24000  # longer than one second of speech


def test_recorded_request_matches_client_body(
    cache: AudioCache, recorded_tts_wav: bytes, recorded_tts_meta: dict[str, Any]
) -> None:
    req = recorded_tts_meta["request"]
    assert req["url"] == "https://api.cartesia.ai/tts/bytes"
    assert req["headers"]["Authorization"] == "Bearer <redacted>"
    assert req["headers"]["Cartesia-Version"] == "2026-08-14"
    voice = req["json"]["voice"]["id"]
    text = req["json"]["transcript"]
    assert recorded_tts_meta["voice"]["cloning"] is False

    seen: list[dict[str, Any]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(json.loads(r.content))
        return httpx.Response(200, content=recorded_tts_wav)

    tts = CartesiaTTS(
        "k", cache, voice_default=voice, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    p = tts.synthesize(text, voice)
    assert seen == [req["json"]]
    assert p is not None and p.stem == audio_key(text, voice) == recorded_tts_meta["cache_key"]
    assert p.read_bytes() == recorded_tts_wav


def test_recorded_fixtures_contain_no_secrets(recorded_tts_meta: dict[str, Any]) -> None:
    assert "sk_car" not in json.dumps(recorded_tts_meta)
