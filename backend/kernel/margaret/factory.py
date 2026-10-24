"""Env selection: MockMargaret when `MOCK_MARGARET=1` or no `ANTHROPIC_API_KEY`."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path

from kernel.margaret._cache import ResponseCache, default_llm_cache_root
from kernel.margaret.claude import ClaudeMargaret, make_client
from kernel.margaret.mock import MockMargaret
from kernel.margaret.persona import default_persona_path, load_persona_system
from kernel.margaret.types import Margaret

log = logging.getLogger("second_key.margaret")

DEFAULT_MODEL = "claude-sonnet-5-5"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def persona_path(env: Mapping[str, str]) -> Path:
    override = env.get("MARGARET_PERSONA", "").strip()
    return Path(override) if override else default_persona_path()


def build_margaret(env: Mapping[str, str] | None = None) -> tuple[Margaret, str]:
    """Returns (persona, "mock"|"real"). Never raises on a missing key; degrades to mock."""
    env = os.environ if env is None else env
    path = persona_path(env)
    key = env.get("ANTHROPIC_API_KEY", "").strip()
    if _truthy(env.get("MOCK_MARGARET")) or not key:
        log.info("margaret.build mode=mock reason=%s", "flag" if key else "no_key")
        return MockMargaret(path), "mock"
    model = env.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    cache = ResponseCache(default_llm_cache_root(env), replay_only=_truthy(env.get("DEMO_MODE")))
    log.info("margaret.build mode=real model=%s replay_only=%s", model, cache.replay_only)
    return (
        ClaudeMargaret(
            make_client(key), model=model, cache=cache, persona_system=load_persona_system(path)
        ),
        "real",
    )
