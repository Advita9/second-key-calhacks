"""`GET /health` reports every mode flag honestly."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import deps
from tests.api.conftest import make_client


def test_health_shape(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["policy_version"] == "v1"
    assert body["demo_mode"] is True
    assert body["ops_token"] == "unset"
    assert body["mode"] == {
        "extractor": "mock",
        "margaret": "mock",
        "nessie": "mock",
        "tts": "mock",
        "stt": "mock",
        "room": "memory",
    }


def test_health_reports_ops_token_and_demo_off(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(monkeypatch, OPS_TOKEN="secret-ops", DEMO_MODE="0") as c:
        body = c.get("/health").json()
        assert body["ops_token"] == "set" and body["demo_mode"] is False
        assert "secret-ops" not in c.get("/health").text
    deps.reset()


def test_cors_headers_for_frontend_origin(client: TestClient) -> None:
    r = client.options(
        "/payments",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-ops-token,content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3001"
    assert "x-ops-token" in r.headers["access-control-allow-headers"].lower()
