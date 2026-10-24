"""Memory-mode room router: join, submit, snapshot, WS push, fail closed."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.room_memory_app import create_app
from api.room_ws import RoomHub, StubTurnTaker


class PersuadedTaker:
    """Returns a payment outcome with rule ids so stripping can be checked end to end."""

    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> dict[str, Any]:
        return {
            "margaret_text": "Alright dear, let me call the bank.",
            "margaret_audio_url": "/audio/abc.wav",
            "persuaded": True,
            "payment_id": "pay-1",
            "stage": 60,
            "outcome": {"decision": "HOLD", "rule_ids": ["H-01", "H-02"], "refusal": None},
        }


class BrokenTaker:
    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> dict[str, Any]:
        raise RuntimeError("kernel exploded")


class SlowTaker:
    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> dict[str, Any]:
        time.sleep(0.5)
        return StubTurnTaker().take_turn(room_id, turn_id, player_id, text)


def _wait_outcome(
    client: TestClient, room: str, role: str, token: str, n: int = 1
) -> dict[str, Any]:
    """`token` is the player token for the attacker view (the view is bound to it)."""
    deadline = time.monotonic() + 5
    key = "myOutcomes" if role == "attacker" else "outcomes"
    headers = {"X-Player-Token": token} if role == "attacker" else {}
    while time.monotonic() < deadline:
        snap = client.get(f"/rooms/{room}/snapshot", params={"role": role}, headers=headers).json()
        if len(snap[key]) >= n:
            return dict(snap)
        time.sleep(0.05)
    raise AssertionError("no outcome within 5s")


def test_join_submit_snapshot_stub() -> None:
    with TestClient(create_app()) as client:
        r = client.post("/rooms/demo/join", json={"handle": "alice"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["room_id"] == "DEMO" and len(j["player_id"]) == 64
        r = client.post(
            "/rooms/DEMO/submit",
            json={"text": "This is the IRS."},
            headers={"X-Player-Token": j["player_token"]},
        )
        assert r.status_code == 200, r.text
        snap = _wait_outcome(client, "DEMO", "attacker", j["player_token"])
        assert snap["myOutcomes"][0] == {"turnId": 1, "stage": 10, "decision": "NONE"}
        assert snap["replies"][0]["text"] == StubTurnTaker.line
        assert snap["role"] == "attacker" and snap["backend"] == "memory"


def test_limits_over_http() -> None:
    with TestClient(create_app()) as client:
        tok = client.post("/rooms/DEMO/join", json={"handle": "alice"}).json()["player_token"]
        h = {"X-Player-Token": tok}
        assert (
            client.post("/rooms/DEMO/submit", json={"text": "x" * 401}, headers=h).status_code
            == 400
        )
        assert client.post("/rooms/DEMO/submit", json={"text": "one"}, headers=h).status_code == 200
        r = client.post("/rooms/DEMO/submit", json={"text": "two"}, headers=h)
        assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMIT"
        assert client.post("/rooms/DEMO/submit", json={"text": "x"}).status_code == 401
        assert client.post("/rooms/DEMO/join", json={"handle": "<b>"}).status_code == 400


def test_attacker_never_sees_rule_ids_board_does() -> None:
    with TestClient(create_app(taker=PersuadedTaker())) as client:
        a = client.post("/rooms/DEMO/join", json={"handle": "alice"}).json()
        b = client.post("/rooms/DEMO/join", json={"handle": "bob"}).json()
        client.post(
            "/rooms/DEMO/submit", json={"text": "a"}, headers={"X-Player-Token": a["player_token"]}
        )
        client.post(
            "/rooms/DEMO/submit", json={"text": "b"}, headers={"X-Player-Token": b["player_token"]}
        )
        snap = _wait_outcome(client, "DEMO", "attacker", a["player_token"])
        _wait_outcome(client, "DEMO", "board", "", n=2)
        text = str(snap)
        assert "ruleIds" not in text and "H-01" not in text and "refusal" not in text
        assert [o["turnId"] for o in snap["myOutcomes"]] == [1]
        assert snap["outcomes"] == []
        board = client.get("/rooms/DEMO/snapshot", params={"role": "board"}).json()
        assert sorted(o["ruleIds"] for o in board["outcomes"]) == [
            ["H-01", "H-02"],
            ["H-01", "H-02"],
        ]
        assert board["scoreboard"]["attempts"] == 2
        assert {lb["bestStage"] for lb in board["leaderboard"]} == {60}


@pytest.mark.parametrize("taker", [BrokenTaker(), SlowTaker()])
def test_fail_closed_on_taker_error_or_timeout(taker: Any) -> None:
    hub = RoomHub(taker=taker, turn_timeout_s=0.1)
    with TestClient(create_app(hub=hub)) as client:
        j = client.post("/rooms/DEMO/join", json={"handle": "alice"}).json()
        client.post(
            "/rooms/DEMO/submit", json={"text": "hi"}, headers={"X-Player-Token": j["player_token"]}
        )
        board = _wait_outcome(client, "DEMO", "board", "")
        o = board["outcomes"][0]
        assert o["stage"] == 10 and o["decision"] == "HOLD"
        assert o["refusal"] == "kernel unavailable, fail closed" and o["ruleIds"] == []
        assert board["replies"] == []
        assert board["scoreboard"]["unauthorizedReleases"] == 0


def test_ws_pushes_snapshots_and_accepts_turns() -> None:
    with TestClient(create_app()) as client:
        j = client.post("/rooms/DEMO/join", json={"handle": "alice"}).json()
        with client.websocket_connect(
            f"/ws?room=DEMO&role=attacker&player_token={j['player_token']}"
        ) as ws:
            first = ws.receive_json()
            assert first["type"] == "room" and first["snapshot"]["room"]["code"] == "DEMO"
            ws.send_json(
                {"type": "submit_turn", "text": "hello", "player_token": j["player_token"]}
            )
            seen_outcome = False
            seen_margaret = False
            accepted = False
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "turn_accepted":
                    accepted = True
                elif msg["type"] == "margaret":
                    seen_margaret = msg["text"] == StubTurnTaker.line
                elif msg["type"] == "room" and msg["snapshot"]["myOutcomes"]:
                    seen_outcome = True
                    assert "ruleIds" not in str(msg)
                if seen_outcome and seen_margaret and accepted:
                    break
            assert accepted and seen_outcome and seen_margaret
            ws.send_json(
                {"type": "submit_turn", "text": "again", "player_token": j["player_token"]}
            )
            for _ in range(5):
                msg = ws.receive_json()
                if msg["type"] == "error":
                    assert msg["code"] == "RATE_LIMIT"
                    break
            else:
                raise AssertionError("expected RATE_LIMIT error over ws")


def test_broadcast_event_relays_kernel_messages() -> None:
    hub = RoomHub()
    with TestClient(create_app(hub=hub)) as client:
        with client.websocket_connect("/ws?room=DEMO&role=board") as ws:
            ws.receive_json()
            hub.broadcast_event({"type": "attack", "name": "replay", "invariant": "I3_REPLAY"})
            msg = ws.receive_json()
            assert msg == {"type": "attack", "name": "replay", "invariant": "I3_REPLAY"}
