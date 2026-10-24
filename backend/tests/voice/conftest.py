"""Voice test fixtures. No network: every HTTP call goes through httpx.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kernel.voice.cache import AudioCache

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "audio"


@pytest.fixture
def cache(tmp_path: Path) -> AudioCache:
    return AudioCache(tmp_path / "audio")


@pytest.fixture
def say_wav() -> bytes:
    data = (FIXTURES / "say_sample.wav").read_bytes()
    assert data.startswith(b"RIFF")
    return data


@pytest.fixture
def clip_webm() -> bytes:
    return (FIXTURES / "clip.webm").read_bytes()


@pytest.fixture
def stt_response() -> dict[str, object]:
    body: dict[str, object] = json.loads((FIXTURES / "stt_response.json").read_text())
    return body


@pytest.fixture
def recorded_tts_wav() -> bytes:
    """Recorded body of one live Cartesia POST /tts/bytes (see tts_recorded.json)."""
    return (FIXTURES / "tts_bytes.wav").read_bytes()


@pytest.fixture
def recorded_tts_meta() -> dict[str, object]:
    meta: dict[str, object] = json.loads((FIXTURES / "tts_recorded.json").read_text())
    return meta
