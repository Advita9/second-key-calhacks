"""Pick the extractor from the environment. Mock unless a key is present and mocks are off."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Literal

from kernel.llm.cache import ResponseCache, default_cache_root
from kernel.llm.claude_extractor import ClaudeExtractor, make_client
from kernel.llm.mock_extractor import MockExtractor
from kernel.llm.types import Extractor

log = logging.getLogger("second_key.llm.factory")

DEFAULT_MODEL = "claude-sonnet-5-5"
_TRUE = {"1", "true", "yes", "on"}


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


CacheMode = Literal["auto", "replay", "live"]
_CACHE_MODES: frozenset[str] = frozenset({"auto", "replay", "live"})


def cache_mode(env: Mapping[str, str]) -> CacheMode:
    """`LLM_CACHE_MODE`: auto (default; cache first, network on a miss when a key exists),
    replay (cache only; a miss fails closed), live (skip cache reads, still write). The old
    `LLM_CACHE_WARM=1` is an alias for auto. DEMO_MODE does not imply replay: `scripts/demo.py`
    sets LLM_CACHE_MODE=replay itself when it must stay offline."""
    raw = env.get("LLM_CACHE_MODE", "").strip().lower()
    if raw in _CACHE_MODES:
        return raw  # type: ignore[return-value]
    if raw:
        log.warning("llm.cache_mode.unknown", extra={"value": raw[:32]})
    return "auto"


class _LiveCache(ResponseCache):
    """`live`: never serve from disk (every lookup is a miss) but keep writing through."""

    def get(self, k: str) -> dict[str, Any] | None:
        self._count("misses")
        return None


def build_cache(env: Mapping[str, str]) -> ResponseCache:
    mode = cache_mode(env)
    root = default_cache_root(env)
    if mode == "live":
        return _LiveCache(root, replay_only=False)
    return ResponseCache(root, replay_only=mode == "replay")


def build_extractor(env: Mapping[str, str]) -> tuple[Extractor, str]:
    """Returns (extractor, "mock"|"real"). The disk cache follows `LLM_CACHE_MODE`."""
    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if truthy(env.get("MOCK_EXTRACTOR")) or not api_key:
        log.info(
            "extractor.mode", extra={"mode": "mock", "reason": "flag" if api_key else "no_key"}
        )
        return MockExtractor(), "mock"
    model = env.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    effort = env.get("ANTHROPIC_EFFORT", "").strip() or None
    cache = build_cache(env)
    log.info(
        "extractor.mode",
        extra={
            "mode": "real",
            "model": model,
            "llm_cache": cache_mode(env),
            "replay_only": cache.replay_only,
            "effort": effort,
        },
    )
    return (
        ClaudeExtractor(make_client(api_key), model=model, cache=cache, effort=effort),
        "real",
    )
