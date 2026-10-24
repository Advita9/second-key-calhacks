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
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger("second_key.llm.cache")

# Process-wide counters across every ResponseCache instance (the extractor and Margaret each
# own one). `scripts/demo.py` reads these to prove a replay run made zero network calls.
_TOTALS: dict[str, int] = {"hits": 0, "misses": 0, "puts": 0}
_TOTALS_LOCK = threading.Lock()


def _bump(field: str) -> None:
    with _TOTALS_LOCK:
        _TOTALS[field] += 1


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
        self._stats: dict[str, int] = {"hits": 0, "misses": 0, "puts": 0}
        self._stats_lock = threading.Lock()

    # ---------------------------------------------------------------- counters

    def stats(self) -> dict[str, int]:
        """Hits, misses and puts seen by this instance."""
        with self._stats_lock:
            return dict(self._stats)

    def _count(self, field: str) -> None:
        with self._stats_lock:
            self._stats[field] += 1
        _bump(field)

    @staticmethod
    def totals() -> dict[str, int]:
        """Hits, misses and puts across every instance in this process."""
        with _TOTALS_LOCK:
            return dict(_TOTALS)

    @staticmethod
    def reset_totals() -> None:
        with _TOTALS_LOCK:
            for k in _TOTALS:
                _TOTALS[k] = 0

    def count(self) -> int:
        """Entries on disk. Cheap: one directory listing."""
        try:
            return sum(1 for _ in self.root.glob("*.json"))
        except OSError:
            return 0

    @staticmethod
    def key(
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        schema: Mapping[str, Any],
        *,
        effort: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """sha256 of the canonical request. `v` bumps when the stored value shape changes."""
        canonical = json.dumps(
            {
                "v": 1,
                "model": model,
                "system": system,
                "messages": messages,
                "schema": schema,
                "effort": effort,
                "max_tokens": max_tokens,
            },
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
            self._count("misses")
            return None
        except (OSError, ValueError) as e:
            log.warning("llm.cache.corrupt", extra={"key": k, "error": type(e).__name__})
            self._count("misses")
            return None
        if not isinstance(raw, dict):
            self._count("misses")
            return None
        self._count("hits")
        return raw

    def put(self, k: str, value: dict[str, Any]) -> None:
        """Atomic: unique temp file per writer, then os.replace. Concurrent puts never raise."""
        path = self._path(k)
        self.root.mkdir(parents=True, exist_ok=True)
        body = json.dumps(value, sort_keys=True, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(
            "w", dir=self.root, suffix=".tmp", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(body)
            tmp_name = tmp.name
        try:
            os.replace(tmp_name, path)
        except OSError:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        self._count("puts")
