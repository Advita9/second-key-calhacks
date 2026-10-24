from __future__ import annotations

import io
import shutil
import wave

import pytest

from kernel.voice.cache import AudioCache, audio_key
from kernel.voice.mock import MockTTS, silent_wav
from kernel.voice.types import TTS


def test_silent_wav_is_one_second_24k() -> None:
    data = silent_wav(1.0, 24000)
    assert data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnframes() == 24000
        assert w.getnchannels() == 1


def test_mock_tts_satisfies_protocol(cache: AudioCache) -> None:
    tts: TTS = MockTTS(cache)
    assert tts.is_mock is True
    assert tts.name == "mock"


@pytest.mark.skipif(not shutil.which("/usr/bin/say"), reason="macOS say not available")
def test_mock_tts_renders_riff_wave_and_caches(cache: AudioCache) -> None:
    tts = MockTTS(cache)
    p = tts.synthesize("Hello, dear.", "voice-a")
    assert p is not None and p.is_file()
    data = p.read_bytes()
    assert data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    assert len(data) > 1000
    mtime = p.stat().st_mtime_ns
    again = tts.synthesize("Hello, dear.", "voice-a")
    assert again == p and p.stat().st_mtime_ns == mtime


def test_mock_key_is_namespaced_so_it_never_collides_with_cartesia(cache: AudioCache) -> None:
    tts = MockTTS(cache)
    assert tts.cache_key("hi", "v") == audio_key("hi", "mock:v")
    assert tts.cache_key("hi", "v") != audio_key("hi", "v")


def test_silent_fallback_when_say_missing(
    cache: AudioCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    tts = MockTTS(cache)
    assert tts.tools_available is False
    p = tts.synthesize("anything", "v")
    assert p is not None
    assert p.read_bytes() == silent_wav(1.0, 24000)


def test_render_failure_falls_back_to_silent(
    cache: AudioCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    tts = MockTTS(cache)
    monkeypatch.setattr(MockTTS, "tools_available", property(lambda _self: True))

    def boom(_text: str) -> bytes:
        raise RuntimeError("say exploded")

    monkeypatch.setattr(tts, "_render", boom)
    p = tts.synthesize("x", "v")
    assert p is not None and p.read_bytes() == silent_wav(1.0, 24000)
