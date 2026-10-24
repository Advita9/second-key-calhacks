"""API tests: explicit env (no .env), fresh singletons and a fresh app per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.main import create_app

TEST_ENV = {
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


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> dict[str, str]:
    for k, v in TEST_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AUDIO_CACHE_DIR", str(tmp_path) + "/audio")
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path) + "/llm")
    deps.reset()
    return dict(TEST_ENV)


def make_client(monkeypatch: pytest.MonkeyPatch, **over: str) -> TestClient:
    for k, v in over.items():
        monkeypatch.setenv(k, v)
    deps.reset()
    return TestClient(create_app())


@pytest.fixture
def client(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    with make_client(monkeypatch) as c:
        yield c
    deps.reset()
