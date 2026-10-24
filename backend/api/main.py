"""FastAPI entrypoint. Only /health for now; payment routes land in a later task."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

log = logging.getLogger("second_key.api")

app = FastAPI(title="Second Key kernel", version="0.1.0")


def _mode() -> dict[str, str]:
    # Every provider is mocked until its client lands. Env switches are wired later.
    return {"extractor": "mock", "tts": "mock", "nessie": "mock", "room": "memory"}


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "mode": _mode(),
        "policy_version": os.environ.get("POLICY_VERSION", "v1"),
    }
