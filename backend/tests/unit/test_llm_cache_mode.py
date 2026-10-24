"""LLM_CACHE_MODE selection and the live / replay cache behaviours (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.llm.cache import ResponseCache
from kernel.llm.factory import build_cache, cache_mode


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "auto"),
        ({"LLM_CACHE_MODE": "auto"}, "auto"),
        ({"LLM_CACHE_MODE": "REPLAY"}, "replay"),
        ({"LLM_CACHE_MODE": " live "}, "live"),
        ({"LLM_CACHE_MODE": "bogus"}, "auto"),
        ({"LLM_CACHE_WARM": "1"}, "auto"),  # legacy alias
        ({"DEMO_MODE": "1"}, "auto"),  # DEMO_MODE no longer implies replay
        ({"DEMO_MODE": "1", "LLM_CACHE_WARM": "0"}, "auto"),
        ({"DEMO_MODE": "1", "LLM_CACHE_MODE": "replay"}, "replay"),
        ({"LLM_CACHE_WARM": "1", "LLM_CACHE_MODE": "replay"}, "replay"),  # explicit wins
    ],
)
def test_cache_mode_parsing(env: dict[str, str], expected: str) -> None:
    assert cache_mode(env) == expected


def test_replay_cache_is_replay_only(tmp_path: Path) -> None:
    env = {"LLM_CACHE_MODE": "replay", "LLM_CACHE_DIR": str(tmp_path)}
    cache = build_cache(env)
    assert cache.replay_only is True
    assert (
        cache_mode({"LLM_CACHE_MODE": "auto"}) == "auto"
        and build_cache({"LLM_CACHE_MODE": "auto", "LLM_CACHE_DIR": str(tmp_path)}).replay_only
        is False
    )


def test_live_cache_skips_reads_but_writes(tmp_path: Path) -> None:
    key = "ab" * 32
    plain = ResponseCache(tmp_path, replay_only=False)
    plain.put(key, {"parsed": {"x": 1}})
    assert plain.get(key) == {"parsed": {"x": 1}}
    live = build_cache({"LLM_CACHE_MODE": "live", "LLM_CACHE_DIR": str(tmp_path)})
    assert live.replay_only is False
    ResponseCache.reset_totals()
    assert live.get(key) is None  # a hit on disk is still a miss in live mode
    live.put(key, {"parsed": {"x": 2}})
    assert plain.get(key) == {"parsed": {"x": 2}}  # the write went through
    totals = ResponseCache.totals()
    assert totals["misses"] == 1 and totals["puts"] == 1
