"""Process settings from the environment.

The repo `.env` is read with python-dotenv into a plain mapping (never exported into
`os.environ`, so a key in `.env` cannot leak into child processes). Real environment
variables override file values. Set `KERNEL_LOAD_DOTENV=0` to skip the file (tests set every
variable explicitly).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
DEFAULT_DB = BACKEND_DIR / "second_key.db"
DEFAULT_POLICY = BACKEND_DIR / "kernel" / "policy" / "v1.yaml"
DEFAULT_EVAL_RESULTS = REPO_DIR / "eval" / "latest.json"
_TRUE = {"1", "true", "yes", "on"}


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUE


def load_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """`.env` values under the real environment. Only strings; blank lines dropped."""
    environ = os.environ if environ is None else environ
    merged: dict[str, str] = {}
    if environ.get("KERNEL_LOAD_DOTENV", "1").strip() != "0":
        env_file = REPO_DIR / ".env"
        if env_file.is_file():
            for k, v in dotenv_values(env_file).items():
                if v is not None:
                    merged[k] = v
    merged.update({k: v for k, v in environ.items() if isinstance(v, str)})
    return merged


@dataclass(frozen=True)
class Settings:
    env: Mapping[str, str]
    demo_mode: bool
    ops_token: str
    kernel_db: str
    policy_path: Path
    eval_results_path: Path
    room_backend: str
    frontend_origin: str

    @property
    def ops_token_set(self) -> bool:
        return bool(self.ops_token)

    def cors_origins(self) -> list[str]:
        origins = ["http://localhost:3001", "http://127.0.0.1:3001"]
        if self.frontend_origin and self.frontend_origin not in origins:
            origins.append(self.frontend_origin)
        return origins


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = load_env(environ)
    db = env.get("KERNEL_DB", "").strip() or str(DEFAULT_DB)
    if db != ":memory:" and not Path(db).is_absolute():
        db = str((REPO_DIR / db).resolve())
    policy = env.get("KERNEL_POLICY", "").strip()
    eval_path = env.get("EVAL_RESULTS", "").strip()
    room = env.get("ROOM_BACKEND", "").strip().lower() or "memory"
    return Settings(
        env=env,
        demo_mode=truthy(env.get("DEMO_MODE")),
        ops_token=env.get("OPS_TOKEN", "").strip(),
        kernel_db=db,
        policy_path=Path(policy) if policy else DEFAULT_POLICY,
        eval_results_path=Path(eval_path) if eval_path else DEFAULT_EVAL_RESULTS,
        room_backend="spacetime" if room == "spacetime" else "memory",
        frontend_origin=env.get("FRONTEND_ORIGIN", "").strip().rstrip("/"),
    )
