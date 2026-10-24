"""Disk cache for model responses, keyed by sha256 of the full canonical request.

Files live under `backend/cache/llm/<key>.json` (gitignored). `replay_only=True` (DEMO_MODE)
means a miss is a failure, so the demo never makes a network call. Values stored are the
model's parsed JSON and stop reason only; prompts and keys are never written.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger("second_key.llm.cache")


def default_cache_root(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("LLM_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    # backend/kernel/llm/cache.py -> backend/cache/llm
    return Path(__file__).resolve().parents[2] / "cache" / "llm"


class ResponseCache:
    def __init__(self, root: Path, *, replay_only: bool) -> None:
        self.root = Path(root)
        self.replay_only = replay_only

    @staticmethod
    def key(
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema: Mapping[str, Any],
    ) -> str:
        canonical = json.dumps(
            {"model": model, "system": system, "messages": messages, "schema": schema},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path(self, k: str) -> Path:
        if not k.isalnum():
            raise ValueError("cache key must be hex")
        return self.root / f"{k}.json"

    def get(self, k: str) -> dict[str, Any] | None:
        path = self._path(k)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            log.warning("llm.cache.corrupt", extra={"key": k, "error": type(e).__name__})
            return None
        if not isinstance(raw, dict):
            return None
        return raw

    def put(self, k: str, value: dict[str, Any]) -> None:
        path = self._path(k)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
