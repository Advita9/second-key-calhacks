from __future__ import annotations

from pathlib import Path

import pytest

from kernel.voice.cartesia import DEFAULT_VOICE_ID, CartesiaSTT, CartesiaTTS
from kernel.voice.factory import make_stt, make_tts, voice_id, voice_mode
from kernel.voice.mock import MockSTT, MockTTS


def test_default_is_mock(tmp_path: Path) -> None:
    env = {"AUDIO_CACHE_DIR": str(tmp_path)}
    assert isinstance(make_tts(env), MockTTS)
    assert isinstance(make_stt(env), MockSTT)
    assert voice_mode(env) == {"tts": "mock", "stt": "mock"}


def test_cartesia_with_key_is_real(tmp_path: Path) -> None:
    env = {
        "AUDIO_CACHE_DIR": str(tmp_path),
        "TTS_PROVIDER": "cartesia",
        "STT_PROVIDER": "cartesia",
        "CARTESIA_API_KEY": "sk_car_x",
        "CARTESIA_VOICE_ID": "abc",
    }
    tts = make_tts(env)
    assert isinstance(tts, CartesiaTTS) and tts.voice_default == "abc"
    assert isinstance(make_stt(env), CartesiaSTT)
    assert voice_mode(env) == {"tts": "real", "stt": "real"}


def test_cartesia_without_key_degrades_to_mock_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = {"AUDIO_CACHE_DIR": str(tmp_path), "TTS_PROVIDER": "cartesia", "STT_PROVIDER": "cartesia"}
    with caplog.at_level("WARNING", logger="second_key.voice"):
        assert isinstance(make_tts(env), MockTTS)
        assert isinstance(make_stt(env), MockSTT)
    assert "CARTESIA_API_KEY is empty" in caplog.text
    assert voice_mode(env) == {"tts": "mock", "stt": "mock"}


def test_mixed_providers(tmp_path: Path) -> None:
    env = {"AUDIO_CACHE_DIR": str(tmp_path), "TTS_PROVIDER": "cartesia", "CARTESIA_API_KEY": "k"}
    assert voice_mode(env) == {"tts": "real", "stt": "mock"}


def test_unknown_provider_is_mock(tmp_path: Path) -> None:
    env = {"AUDIO_CACHE_DIR": str(tmp_path), "TTS_PROVIDER": "elevenlabs", "CARTESIA_API_KEY": "k"}
    assert isinstance(make_tts(env), MockTTS)


def test_voice_id_default_is_michelle() -> None:
    assert voice_id({}) == DEFAULT_VOICE_ID == "d7bf7d75-64b7-4c1e-86c0-79d647366587"
    assert voice_id({"CARTESIA_VOICE_ID": " z "}) == "z"
