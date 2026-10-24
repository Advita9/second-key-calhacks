from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kernel.voice.cache import AudioCache, audio_key, audio_url, default_cache_root, is_audio_key


def test_same_text_and_voice_same_key() -> None:
    assert audio_key("hello", "v1") == audio_key("hello", "v1")


def test_different_voice_different_key() -> None:
    assert audio_key("hello", "v1") != audio_key("hello", "v2")


def test_different_text_different_key() -> None:
    assert audio_key("hello", "v1") != audio_key("hello.", "v1")


def test_key_is_sha256_of_text_nul_voice() -> None:
    expected = hashlib.sha256(b"hello\x00v1").hexdigest()
    assert audio_key("hello", "v1") == expected
    assert is_audio_key(expected)


def test_separator_prevents_boundary_collisions() -> None:
    assert audio_key("ab", "c") != audio_key("a", "bc")


def test_cache_put_get_roundtrip(cache: AudioCache) -> None:
    key = audio_key("x", "v")
    assert cache.get(key) is None
    p = cache.put(key, b"RIFF....")
    assert p == cache.root / f"{key}.wav"
    assert cache.get(key) == p
    assert cache.count() == 1
    assert cache.size_bytes() == 8
    assert not list(cache.root.glob("*.tmp"))


def test_cache_rejects_bad_key(cache: AudioCache) -> None:
    with pytest.raises(ValueError):
        cache.path("../etc/passwd")
    assert not is_audio_key("ABC")


def test_audio_url_from_path_or_key() -> None:
    key = audio_key("x", "v")
    assert audio_url(key) == f"/audio/{key}.wav"
    assert audio_url(Path("/tmp") / f"{key}.wav") == f"/audio/{key}.wav"


def test_default_cache_root(tmp_path: Path) -> None:
    assert default_cache_root({}).parts[-2:] == ("cache", "audio")
    assert default_cache_root({"AUDIO_CACHE_DIR": str(tmp_path)}) == tmp_path
