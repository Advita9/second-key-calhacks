"""Provider selection from env. `cartesia` without a key degrades to mock with a warning."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from kernel.voice.cache import AudioCache, default_cache_root
from kernel.voice.cartesia import DEFAULT_VOICE_ID, CartesiaSTT, CartesiaTTS
from kernel.voice.mock import MockSTT, MockTTS
from kernel.voice.types import STT, TTS

log = logging.getLogger("second_key.voice")

Env = Mapping[str, str]


def _env(env: Env | None) -> Env:
    return os.environ if env is None else env


def _provider(env: Env, var: str) -> str:
    value = env.get(var, "mock").strip().lower() or "mock"
    if value not in {"mock", "cartesia"}:
        log.warning("%s=%r is not mock|cartesia; using mock", var, value)
        return "mock"
    return value


def _real(env: Env, var: str) -> bool:
    if _provider(env, var) != "cartesia":
        return False
    if not env.get("CARTESIA_API_KEY", "").strip():
        log.warning("%s=cartesia but CARTESIA_API_KEY is empty; using mock", var)
        return False
    return True


def voice_id(env: Env | None = None) -> str:
    return _env(env).get("CARTESIA_VOICE_ID", "").strip() or DEFAULT_VOICE_ID


def make_tts(env: Env | None = None, cache: AudioCache | None = None) -> TTS:
    env = _env(env)
    cache = cache or AudioCache(default_cache_root(dict(env)))
    if _real(env, "TTS_PROVIDER"):
        return CartesiaTTS(env["CARTESIA_API_KEY"].strip(), cache, voice_default=voice_id(env))
    return MockTTS(cache)


def make_stt(env: Env | None = None) -> STT:
    env = _env(env)
    if _real(env, "STT_PROVIDER"):
        return CartesiaSTT(env["CARTESIA_API_KEY"].strip())
    return MockSTT()


def voice_mode(env: Env | None = None) -> dict[str, str]:
    """For `/health.mode`: {"tts": "real"|"mock", "stt": "real"|"mock"}."""
    env = _env(env)
    return {
        "tts": "real" if _real(env, "TTS_PROVIDER") else "mock",
        "stt": "real" if _real(env, "STT_PROVIDER") else "mock",
    }
