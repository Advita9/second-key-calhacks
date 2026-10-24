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


def test_health_reports_audit_anchor_mismatch_on_file_db(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    import json
    from pathlib import Path

    from tests.api.test_flow import scenario_b_body

    db = Path(str(tmp_path)) / "kernel.db"
    with make_client(monkeypatch, KERNEL_DB=str(db)) as c:
        assert c.post("/payments", json=scenario_b_body()).status_code == 200
        assert c.get("/health").json()["audit"]["anchor"] == "ok"
    deps.reset()
    sidecar = Path(f"{db}.head.json")
    assert sidecar.is_file()
    sidecar.write_text(json.dumps({"seq": 1, "hash": "0" * 64}))  # the table moved on
    with make_client(monkeypatch, KERNEL_DB=str(db)) as c:
        h = c.get("/health")
        assert h.status_code == 200
        assert h.json()["ok"] is True and h.json()["audit"]["anchor"] == "mismatch"
        assert c.get("/audit/verify").json()["anchor"] == "mismatch"
        # Writes are refused with a readable shape, not a 500.
        r = c.post("/payments", json=scenario_b_body())
        assert r.status_code == 503 and r.json()["invariant"] == "AUDIT_ANCHOR_MISMATCH"
        assert c.post("/audit/acknowledge", json={"actor_id": "ops_1"}).status_code == 200
        assert c.get("/health").json()["audit"]["anchor"] == "ok"
        assert c.post("/payments", json=scenario_b_body()).status_code == 200
    deps.reset()
