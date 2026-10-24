"""On-disk audio cache keyed by sha256(text + "\\x00" + voice_id).

Files live under `backend/cache/audio/<key>.wav` (gitignored). Override the root with
`AUDIO_CACHE_DIR`. Writes are atomic (temp file then rename) so a half-written file is
never served.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


def audio_key(text: str, voice_id: str) -> str:
    """Stable cache key. Same text and voice give the same key; any change gives a new one."""
    return hashlib.sha256((text + "\x00" + voice_id).encode("utf-8")).hexdigest()


def is_audio_key(key: str) -> bool:
    return bool(_KEY_RE.match(key))


def audio_url(path_or_key: Path | str) -> str:
    """Public URL for a cached file, served by `GET /audio/{key}.wav`."""
    key = path_or_key.stem if isinstance(path_or_key, Path) else path_or_key
    return f"/audio/{key}.wav"


def default_cache_root(env: dict[str, str] | os._Environ[str] | None = None) -> Path:
    env = os.environ if env is None else env
    override = env.get("AUDIO_CACHE_DIR")
    if override:
        return Path(override)
    # backend/kernel/voice/cache.py -> backend/cache/audio
    return Path(__file__).resolve().parents[2] / "cache" / "audio"


class AudioCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if not is_audio_key(key):
            raise ValueError("audio key must be 64 lowercase hex characters")
        return self.root / f"{key}.wav"

    def get(self, key: str) -> Path | None:
        p = self.path(key)
        return p if p.is_file() and p.stat().st_size > 0 else None

    def put(self, key: str, wav: bytes) -> Path:
        p = self.path(key)
        tmp = p.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_bytes(wav)
        os.replace(tmp, p)
        return p

    def count(self) -> int:
        return sum(1 for _ in self.root.glob("*.wav"))

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.glob("*.wav"))
