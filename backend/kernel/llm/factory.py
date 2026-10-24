"""Pick the extractor from the environment. Mock unless a key is present and mocks are off."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from kernel.llm.cache import ResponseCache, default_cache_root
from kernel.llm.claude_extractor import ClaudeExtractor, make_client
from kernel.llm.mock_extractor import MockExtractor
from kernel.llm.types import Extractor

log = logging.getLogger("second_key.llm.factory")

DEFAULT_MODEL = "claude-sonnet-5-5"
_TRUE = {"1", "true", "yes", "on"}


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def build_extractor(env: Mapping[str, str]) -> tuple[Extractor, str]:
    """Returns (extractor, "mock"|"real"). DEMO_MODE makes the real one replay-only."""
    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if truthy(env.get("MOCK_EXTRACTOR")) or not api_key:
        log.info(
            "extractor.mode", extra={"mode": "mock", "reason": "flag" if api_key else "no_key"}
        )
        return MockExtractor(), "mock"
    model = env.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    replay_only = truthy(env.get("DEMO_MODE"))
    effort = env.get("ANTHROPIC_EFFORT", "").strip() or None
    cache = ResponseCache(default_cache_root(env), replay_only=replay_only)
    log.info(
        "extractor.mode",
        extra={"mode": "real", "model": model, "replay_only": replay_only, "effort": effort},
    )
    return (
        ClaudeExtractor(make_client(api_key), model=model, cache=cache, effort=effort),
        "real",
    )
