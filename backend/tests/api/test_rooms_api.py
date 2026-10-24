"""`POST /rooms/{room}/turns` (bridge JSON and multipart) and `/rooms/{room}/reset`."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.room_ws import TURN_TIMEOUT_S
from tests.api.conftest import make_client
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
        data={"turn_id": "m2", "player_id": "p2", "text": "hint text"},
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64, "audio/webm")},
    )
    assert r.status_code == 200 and set(r.json()) == SHAPE


def test_player_form_path_gets_public_outcome_only(client: TestClient) -> None:
    for i, t in enumerate(WARM_FEAR[:-1]):
        turn(client, t, i)
    r = client.post(
        "/rooms/DEMO/turns", data={"turn_id": "f", "player_id": "ptt", "text": WARM_FEAR[-1]}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == 70 and body["payment_id"]
    assert body["outcome"] == {"decision": "HOLD", "refusal": None}
    assert "rule_ids" not in body["outcome"] and "H-01" not in r.text


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


def test_turns_route_limits(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    tok = "bridge-secret"
    with make_client(monkeypatch, BRIDGE_TOKEN=tok) as c:
        ok = {"turn_id": "1", "player_id": "p", "text": "hello"}
        # Bridge JSON path needs the bridge token when set; form path never does.
        assert c.post("/rooms/DEMO/turns", json=ok).status_code == 401
        assert (
            c.post("/rooms/DEMO/turns", json=ok, headers={"X-Ops-Token": "nope"}).status_code == 401
        )
        assert (
            c.post("/rooms/DEMO/turns", json=ok, headers={"X-Bridge-Token": tok}).status_code == 200
        )
        assert c.post("/rooms/DEMO/turns", data={**ok, "player_id": "form1"}).status_code == 200
        # 400 chars max on both paths.
        long = {**ok, "text": "x" * 401}
        assert (
            c.post("/rooms/DEMO/turns", json=long, headers={"X-Bridge-Token": tok}).status_code
            == 422
        )
        assert c.post("/rooms/DEMO/turns", data={**long, "player_id": "form2"}).status_code == 400
        assert (
            c.post(
                "/rooms/DEMO/turns", json={**ok, "text": "y" * 400}, headers={"X-Bridge-Token": tok}
            ).status_code
            == 200
        )
        # Room code rule: 3 to 16 of [A-Z0-9-].
        for bad in ("ab", "x" * 17, "bad%20code", "room_1"):
            r = c.post(f"/rooms/{bad}/turns", json=ok, headers={"X-Bridge-Token": tok})
            assert r.status_code == 400, bad
        assert c.post("/rooms/ab/reset").status_code == 400
    deps.reset()


def test_hub_turn_timeout_covers_real_budgets() -> None:
    # Margaret 12 s + extractor 8 s + TTS 4 s + slack.
    assert TURN_TIMEOUT_S >= 12.0 + 8.0 + 4.0 + 1.0


def test_reset_cancels_open_room_payment(client: TestClient) -> None:
    last = [turn(client, t, i) for i, t in enumerate(WARM_FEAR)][-1]
    pid = last["payment_id"]
    assert pid and client.get(f"/payments/{pid}").json()["state"] == "HELD"
    r = client.post("/rooms/DEMO/reset")
    assert r.status_code == 200 and r.json()["cancelled_payment_id"] == pid
    rec = client.get(f"/payments/{pid}").json()
    assert rec["state"] == "CANCELLED"
    assert any(h["kind"] == "CANCELLED" for h in rec["history"])
    r = client.post(
        f"/payments/{pid}/attest", json={"actor_id": "ops_1", "capability": "BANK_REVIEW"}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NOT_ELIGIBLE"
    # A second reset has nothing to cancel.
    assert client.post("/rooms/DEMO/reset").json()["cancelled_payment_id"] is None


def test_form_path_rate_limited_per_player(client: TestClient) -> None:
    from api.routes.rooms import TurnRateLimiter, form_limiter

    body = {"turn_id": "r1", "player_id": "burst", "text": "hello"}
    assert client.post("/rooms/DEMO/turns", data=body).status_code == 200
    r = client.post("/rooms/DEMO/turns", data={**body, "turn_id": "r2"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMIT"
    # Another player in the same room is not affected; the bridge JSON path is not limited.
    assert client.post("/rooms/DEMO/turns", data={**body, "player_id": "other"}).status_code == 200
    for i in range(3):
        j = {"turn_id": f"b{i}", "player_id": "burst", "text": "hello"}
        assert client.post("/rooms/DEMO/turns", json=j).status_code == 200
    # The window is 3 s on a monotonic clock.
    lim = TurnRateLimiter()
    lim.check("DEMO", "x", now=100.0)
    with pytest.raises(Exception, match="429|RATE_LIMIT"):
        lim.check("DEMO", "x", now=102.9)
    lim.check("DEMO", "x", now=103.0)
    assert form_limiter.interval_s == 3.0
