"""Env selection: MockMargaret when `MOCK_MARGARET=1` or no `ANTHROPIC_API_KEY`."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from kernel.llm.cache import ResponseCache, default_cache_root
from kernel.margaret.claude import ClaudeMargaret, make_client
from kernel.margaret.mock import MockMargaret
from kernel.margaret.persona import default_persona_path, load_persona_system
from kernel.margaret.types import Margaret

log = logging.getLogger("second_key.margaret")

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT_S = 12.0  # Margaret gets more than the extractor's 7 s; still fail-closed


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def persona_path(env: Mapping[str, str]) -> Path:
    override = env.get("MARGARET_PERSONA", "").strip()
    return Path(override) if override else default_persona_path()


def timeout_s_from_env(env: Mapping[str, str]) -> float:
    """`MARGARET_TIMEOUT_S`, default DEFAULT_TIMEOUT_S; garbage or non-positive -> default."""
    raw = env.get("MARGARET_TIMEOUT_S", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_S
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def build_margaret(
    env: Mapping[str, str] | None = None, *, timeout_s: float | None = None
) -> tuple[Margaret, str]:
    """Returns (persona, "mock"|"real"). Never raises on a missing key; degrades to mock.
    `timeout_s` overrides `MARGARET_TIMEOUT_S` (default 12 s, outside the kernel's 8 s
    extractor budget)."""
    env = os.environ if env is None else env
    path = persona_path(env)
    key = env.get("ANTHROPIC_API_KEY", "").strip()
    if _truthy(env.get("MOCK_MARGARET")) or not key:
        log.info("margaret.build mode=mock reason=%s", "flag" if key else "no_key")
        return MockMargaret(path), "mock"
    model = env.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    replay_only = _truthy(env.get("DEMO_MODE")) and not _truthy(env.get("LLM_CACHE_WARM"))
    cache = ResponseCache(default_cache_root(env), replay_only=replay_only)
    t = timeout_s if timeout_s is not None else timeout_s_from_env(env)
    log.info(
        "margaret.build mode=real model=%s replay_only=%s timeout_s=%.1f",
        model,
        cache.replay_only,
        t,
    )
    return (
        ClaudeMargaret(
            make_client(key, timeout=t),
            model=model,
            cache=cache,
            persona_system=load_persona_system(path),
        ),
        "real",
    )
