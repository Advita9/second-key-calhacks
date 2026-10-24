"""Kernel WS `/ws`: payment events after POST /payments, attack events after /attack/replay."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import deps
from tests.api.conftest import make_client
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


def test_attacker_ws_never_receives_payment_or_attack_events(client: TestClient) -> None:
    j = client.post("/rooms/DEMO/join", json={"handle": "mallory"}).json()
    with (
        client.websocket_connect(f"/ws?room=DEMO&role=attacker&player_id={j['player_id']}") as att,
        client.websocket_connect("/ws?room=DEMO&role=board") as board,
    ):
        assert att.receive_json()["type"] == "room"
        assert board.receive_json()["type"] == "room"
        create(client, scenario_b_body())
        client.post("/attack/replay")
        # The board sees both kinds.
        kinds = {_next_of(board, "payment")["type"], _next_of(board, "attack")["type"]}
        assert kinds == {"payment", "attack"}
        # The attacker socket sees nothing from those; a probe margaret event for its own room
        # proves the socket is alive and ordered.
        client.post(
            "/rooms/DEMO/turns", json={"turn_id": "1", "player_id": j["player_id"], "text": "hello"}
        )
        client.post(
            "/rooms/OTHER/turns", json={"turn_id": "2", "player_id": "x", "text": "hello other"}
        )
        seen: list[dict[str, Any]] = []
        for _ in range(10):
            msg = att.receive_json()
            seen.append(msg)
            if msg.get("type") == "margaret":
                break
        types = {m["type"] for m in seen}
        assert types <= {"room", "margaret"}, types
        assert all(m.get("room_id", "DEMO") == "DEMO" for m in seen)
        assert "reasons" not in str(seen) and "I3_REPLAY" not in str(seen)


def test_board_ops_roles_need_token_when_set(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tok = "ops-secret-ws"
    with make_client(monkeypatch, OPS_TOKEN=tok) as c:
        j = c.post("/rooms/DEMO/join", json={"handle": "alice"}).json()
        for role in ("board", "ops"):
            r = c.get("/rooms/DEMO/snapshot", params={"role": role})
            assert r.status_code == 401, role
            r = c.get("/rooms/DEMO/snapshot", params={"role": role, "token": "wrong"})
            assert r.status_code == 401, role
            # Snapshot takes the header only; a query token is ignored (stays out of URL logs).
            r = c.get("/rooms/DEMO/snapshot", params={"role": role, "token": tok})
            assert r.status_code == 401
            r = c.get("/rooms/DEMO/snapshot", params={"role": role}, headers={"X-Ops-Token": tok})
            assert r.status_code == 200 and r.json()["role"] == role
            with c.websocket_connect(f"/ws?room=DEMO&role={role}") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "error" and msg["code"] == "NOT_OPERATOR"
            with c.websocket_connect(f"/ws?room=DEMO&role={role}&token={tok}") as ws:
                assert ws.receive_json()["type"] == "room"
        # Attackers never need it.
        r = c.get("/rooms/DEMO/snapshot", params={"role": "attacker", "player_id": j["player_id"]})
        assert r.status_code == 200 and r.json()["outcomes"] == []
        with c.websocket_connect(f"/ws?room=DEMO&role=attacker&player_id={j['player_id']}") as ws:
            assert ws.receive_json()["type"] == "room"
    deps.reset()


def test_payment_event_carries_display_fields(client: TestClient) -> None:
    with client.websocket_connect("/ws?room=DEMO&role=ops") as ws:
        ws.receive_json()
        create(client, scenario_b_body())
        ev = _next_of(ws, "payment")
        assert ev["amount_cents"] == 800_000 and ev["rail"] == "ACH"
        assert ev["beneficiary"] == {"name": "Bay Roofing", "account_ref": "ext_bay_roofing"}


def test_board_socket_gets_room_push_after_http_join(client: TestClient) -> None:
    import time

    with client.websocket_connect("/ws?room=DEMO&role=board") as ws:
        first = ws.receive_json()
        assert first["type"] == "room" and first["snapshot"]["players"] == []
        started = time.monotonic()
        r = client.post("/rooms/DEMO/join", json={"handle": "alice"})
        assert r.status_code == 200
        msg = _next_of(ws, "room", tries=5)
        assert time.monotonic() - started < 1.0
        assert [p["handle"] for p in msg["snapshot"]["players"]] == ["alice"]
