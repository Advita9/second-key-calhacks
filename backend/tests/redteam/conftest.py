"""Red-team fixtures: a TestClient over the real app, so the whole suite runs in CI with no
external server. Mirrors tests/api/conftest but adds an ops-token variant. The attacks also
run against the manually started port 8020 by hand; these fixtures are the CI-safe path.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import create_app

BASE_ENV = {
    "MOCK_EXTRACTOR": "1",
    "MOCK_MARGARET": "1",
    "DEMO_MODE": "1",
    "KERNEL_DB": ":memory:",
    "ROOM_BACKEND": "memory",
    "TTS_PROVIDER": "mock",
    "STT_PROVIDER": "mock",
    "KERNEL_LOAD_DOTENV": "0",
    "OPS_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
    "NESSIE_API_KEY": "",
    "CARTESIA_API_KEY": "",
}


def _apply_env(monkeypatch: pytest.MonkeyPatch, tmp_path: object, **over: str) -> None:
    for k, v in {**BASE_ENV, **over}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AUDIO_CACHE_DIR", str(tmp_path) + "/audio")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path) + "/llm")
    deps.reset()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> Iterator[TestClient]:
    """App with the operator credential UNSET (local-dev defaults)."""
    _apply_env(monkeypatch, tmp_path)
    with TestClient(create_app()) as c:
        yield c
    deps.reset()


OPS_TOKEN = "rt-secret"


@pytest.fixture
def ops_client(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> Iterator[TestClient]:
    """App with OPS_TOKEN set, so operator routes require the X-Ops-Token header."""
    _apply_env(monkeypatch, tmp_path, OPS_TOKEN=OPS_TOKEN)
    with TestClient(create_app()) as c:
        yield c
    deps.reset()
