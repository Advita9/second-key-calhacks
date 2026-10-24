"""`POST /rooms/{room}/turns` (bridge JSON and multipart) and `/rooms/{room}/reset`."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.unit.test_rooms import WARM_FEAR

SHAPE = {"margaret_text", "margaret_audio_url", "persuaded", "payment_id", "stage", "outcome"}


def turn(client: TestClient, text: str, i: int = 1, room: str = "DEMO") -> dict[str, Any]:
    r = client.post(
        f"/rooms/{room}/turns", json={"turn_id": str(i), "player_id": "player_a", "text": text}
    )
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert set(body) == SHAPE
    return body


def test_turn_shape(client: TestClient) -> None:
    body = turn(client, "Good morning Margaret, how is the garden?")
    assert body["margaret_text"]
    assert body["persuaded"] is False and body["payment_id"] is None
    assert body["stage"] == 10 and body["outcome"] is None
    assert body["margaret_audio_url"] is None or body["margaret_audio_url"].startswith("/audio/")


def test_integer_turn_id_from_bridge(client: TestClient) -> None:
    r = client.post(
        "/rooms/demo/turns", json={"turn_id": 7, "player_id": "p", "text": "hello there"}
    )
    assert r.status_code == 200 and r.json()["stage"] == 10


def test_warm_fear_script_reaches_held_payment_and_resets(client: TestClient) -> None:
    results = [turn(client, t, i) for i, t in enumerate(WARM_FEAR)]
    last = results[-1]
    assert last["persuaded"] is True and last["payment_id"]
    assert last["stage"] == 70
    assert last["outcome"]["decision"] == "HOLD" and "H-01" in last["outcome"]["rule_ids"]
    rec = client.get(f"/payments/{last['payment_id']}").json()
    assert rec["state"] == "HELD" and rec["conversation_id"] == "room_DEMO"
    assert rec["decision"]["signals"], "signals should cite the room transcript"
    # Ops lifts the hold; the next turn reports stage 90.
    r = client.post(
        f"/payments/{last['payment_id']}/attest",
        json={"actor_id": "ops_1", "capability": "BANK_REVIEW"},
    )
    assert r.status_code == 200
    assert turn(client, "Thank you grandma.", 9)["stage"] == 90
    # Reset: fresh Margaret, no payment.
    r = client.post("/rooms/DEMO/reset")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["room_id"] == "DEMO"
    after = turn(client, "Hello again.", 10)
    assert after["stage"] == 10 and after["payment_id"] is None


def test_multipart_turn_uses_text_or_stt(client: TestClient) -> None:
    r = client.post(
        "/rooms/DEMO/turns",
        data={"turn_id": "m1", "player_id": "p", "text": "Hello from push to talk"},
    )
    assert r.status_code == 200 and set(r.json()) == SHAPE
    r = client.post(
        "/rooms/DEMO/turns",
        data={"turn_id": "m2", "player_id": "p", "text": "hint text"},
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64, "audio/webm")},
    )
    assert r.status_code == 200 and set(r.json()) == SHAPE


def test_empty_turn_400(client: TestClient) -> None:
    r = client.post("/rooms/DEMO/turns", json={"turn_id": "1", "player_id": "p", "text": "  "})
    assert r.status_code == 400


def test_memory_room_path_uses_real_margaret(client: TestClient) -> None:
    """The memory-mode `/submit` path runs through the SessionStore, not the stub."""
    import time

    j = client.post("/rooms/DEMO/join", json={"handle": "alice"}).json()
    r = client.post(
        "/rooms/DEMO/submit",
        json={"text": "Good morning Margaret"},
        headers={"X-Player-Token": j["player_token"]},
    )
    assert r.status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snap = client.get(
            "/rooms/DEMO/snapshot", params={"role": "attacker", "player_id": j["player_id"]}
        ).json()
        if snap["replies"]:
            break
        time.sleep(0.05)
    assert snap["replies"] and snap["replies"][0]["text"]
    assert snap["myOutcomes"][0]["stage"] == 10
