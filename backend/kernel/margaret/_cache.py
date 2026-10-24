"""Disk cache for Margaret model responses, keyed by sha256 of the full request.

TODO(T5/T6 merge): replace with `kernel.llm.cache.ResponseCache` once it lands; the shape
here (`key`, `get`, `put`, `replay_only`) matches the plan so the swap is an import change.
Values are `{"parsed": <dict>, "stop_reason": <str>}`. Writes are atomic.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def default_llm_cache_root(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("LLM_CACHE_DIR", "")
    if override:
        return Path(override)
    # backend/kernel/margaret/_cache.py -> backend/cache/llm
    return Path(__file__).resolve().parents[2] / "cache" / "llm"


class ResponseCache:
    def __init__(self, root: Path, *, replay_only: bool = False) -> None:
        self.root = root
        self.replay_only = replay_only
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(
        model: str, system: str, messages: Sequence[Mapping[str, Any]], schema: Mapping[str, Any]
    ) -> str:
        payload = {"model": model, "system": system, "messages": list(messages), "schema": schema}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def path(self, k: str) -> Path:
        return self.root / f"{k}.json"

    def get(self, k: str) -> dict[str, Any] | None:
        p = self.path(k)
        if not p.is_file():
            return None
        try:
            loaded = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return loaded if isinstance(loaded, dict) else None

    def put(self, k: str, value: Mapping[str, Any]) -> None:
        p = self.path(k)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(dict(value), sort_keys=True, indent=1), "utf-8")
        os.replace(tmp, p)
