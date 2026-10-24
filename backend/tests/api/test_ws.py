"""Kernel WS `/ws`: payment events after POST /payments, attack events after /attack/replay."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.test_flow import create, scenario_b_body


def _next_of(ws: Any, kind: str, tries: int = 30) -> dict[str, Any]:
    for _ in range(tries):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            out: dict[str, Any] = msg
            return out
    raise AssertionError(f"no {kind} event")


def test_payment_event_after_post(client: TestClient) -> None:
    with client.websocket_connect("/ws?room=DEMO&role=board") as ws:
        first = ws.receive_json()
        assert first["type"] == "room"
        p = create(client, scenario_b_body())
        ev = _next_of(ws, "payment")
        assert ev["payment_id"] == p["id"]
        assert ev["state"] == "ELIGIBLE_TO_SUBMIT"
        assert ev["fingerprint"] == p["fingerprint"]
        assert ev["reasons"] == ["A-01"] and ev["last_refusal"] is None


def test_attack_event_after_replay(client: TestClient) -> None:
    with client.websocket_connect("/ws?room=DEMO&role=board") as ws:
        ws.receive_json()
        r = client.post("/attack/replay")
        assert r.status_code == 200
        ev = _next_of(ws, "attack")
        assert ev == {"type": "attack", "name": "replay", "invariant": "I3_REPLAY"}


def test_refused_release_pushes_last_refusal(client: TestClient) -> None:
    p = create(client, scenario_b_body())
    with client.websocket_connect("/ws?room=DEMO&role=board") as ws:
        ws.receive_json()
        r = client.post(
            f"/payments/{p['id']}/release", json={"certificate_id": "cert_nope", "nonce": "x"}
        )
        assert r.status_code == 409
        ev = _next_of(ws, "payment")
        assert ev["payment_id"] == p["id"] and ev["last_refusal"] == "I1_NO_CERT"
