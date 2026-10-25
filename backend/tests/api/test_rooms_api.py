"""`POST /rooms/{room}/turns` (bridge JSON and multipart) and `/rooms/{room}/reset`."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import deps
from api.room_ws import TURN_TIMEOUT_S
from tests.api.conftest import make_client
from tests.unit.test_rooms import WARM_FEAR
from api.routes import rooms

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
    assert rec["origin"] == "room"
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
            "/rooms/DEMO/snapshot",
            params={"role": "attacker"},
            headers={"X-Player-Token": j["player_token"]},
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
    from api.ratelimit import TurnRateLimiter
    from api.routes.rooms import form_limiter

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
    assert lim.allow("DEMO:x", now=100.0)
    assert not lim.allow("DEMO:x", now=102.9)
    assert lim.allow("DEMO:x", now=103.0)
    assert form_limiter.interval_s == 3.0


def test_scripted_attack_reaches_held_payment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.routes import rooms as rooms_routes

    monkeypatch.setattr(rooms_routes, "SCRIPTED_PAUSE_S", 0.0)
    with client.websocket_connect("/ws?room=DEMO&role=board") as ws:
        ws.receive_json()
        r = client.post("/rooms/DEMO/scripted-attack")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["payment_id"] and body["decision"] == "HOLD" and body["stage"] == 70
        assert body["origin"] == "room" and body["player_id"] == "scripted-demo"
        assert len(body["turns"]) == 3
        assert [t["turn_id"] for t in body["turns"]] == ["scripted-1", "scripted-2", "scripted-3"]
        assert body["turns"][-1]["payment_id"] == body["payment_id"]
        assert all(t["margaret_text"] for t in body["turns"])
        rec = client.get(f"/payments/{body['payment_id']}").json()
        assert rec["state"] == "HELD" and rec["origin"] == "room"
        assert rec["beneficiary"]["name"] == "Agent Daniels" and rec["rail"] == "WIRE"
        assert rec["amount_cents"] == 185_000
        # One margaret event per turn on the kernel WS, plus the payment card.
        seen: list[dict[str, object]] = []
        for _ in range(12):
            m = ws.receive_json()
            seen.append(m)
            if len([x for x in seen if x["type"] == "margaret"]) == 3:
                break
        margaret = [x for x in seen if x["type"] == "margaret"]
        assert len(margaret) == 3 and all(x.get("scripted") is True for x in margaret)
        assert any(x["type"] == "payment" for x in seen)
    # One run per 30 s per room; another room is independent.
    r = client.post("/rooms/DEMO/scripted-attack")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMIT"
    assert client.post("/rooms/OTHER/scripted-attack").status_code == 200
    # The room's leaderboard is untouched: no memory-room turn rows were written.
    snap = client.get("/rooms/DEMO/snapshot", params={"role": "board"}).json()
    assert snap["turns"] == [] and snap["leaderboard"] == []


def test_scripted_attack_needs_ops_token_when_set(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.routes import rooms as rooms_routes

    monkeypatch.setattr(rooms_routes, "SCRIPTED_PAUSE_S", 0.0)
    tok = "ops-secret-script"
    with make_client(monkeypatch, OPS_TOKEN=tok) as c:
        assert c.post("/rooms/DEMO/scripted-attack").status_code == 401
        assert c.get("/payments", headers={"X-Ops-Token": tok}).json()["payments"] == []
        r = c.post("/rooms/DEMO/scripted-attack", headers={"X-Ops-Token": tok})
        assert r.status_code == 200 and r.json()["decision"] == "HOLD"
    deps.reset()


def test_form_path_rate_limited_per_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotating player_id does not buy more turns: a burst of 3 per 3 s per peer address."""
    from api.ratelimit import ADDRESS_BURST, WindowLimiter

    import api.ratelimit as ratelimit

    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: 100.0)

    codes = [
        client.post("/rooms/ADDR1/turns", data={"text": "hello", "player_id": f"r{i}"}).status_code
        for i in range(ADDRESS_BURST + 2)
    ]

    print("RATE LIMIT DEBUG:", codes)
    print(
        "ADDRESS HITS:",
        rooms.form_address_limiter._hits,
    )
    assert codes[:ADDRESS_BURST] == [200] * ADDRESS_BURST and set(codes[ADDRESS_BURST:]) == {429}
    # The bridge JSON path is not address-limited (it is token-gated instead).
    for i in range(ADDRESS_BURST + 2):
        j = {"turn_id": f"j{i}", "player_id": "bridge", "text": "hello"}
        assert client.post("/rooms/ADDR1/turns", json=j).status_code == 200
    w = WindowLimiter(2, 10.0)
    assert w.allow("k", now=0.0) and w.allow("k", now=1.0) and not w.allow("k", now=2.0)
    assert w.allow("k", now=10.0)  # the first hit slid out of the window


def test_join_flood_and_memory_submit_are_address_limited(client: TestClient) -> None:
    from api.ratelimit import ADDRESS_BURST, JOIN_BURST

    tokens = []
    for i in range(JOIN_BURST):
        r = client.post("/rooms/FLOOD2/join", json={"handle": f"h{i}"})
        assert r.status_code == 200, r.text
        tokens.append(r.json()["player_token"])
    r = client.post("/rooms/FLOOD2/join", json={"handle": "one-too-many"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "RATE_LIMIT"
    codes = [
        client.post(
            "/rooms/FLOOD2/submit", json={"text": "hello"}, headers={"X-Player-Token": t}
        ).status_code
        for t in tokens
    ]
    assert codes[:ADDRESS_BURST] == [200] * ADDRESS_BURST and 429 in codes[ADDRESS_BURST:]


def test_attacker_views_are_bound_to_the_player_token(client: TestClient) -> None:
    eve = client.post("/rooms/BIND1/join", json={"handle": "eve"}).json()
    bob = client.post("/rooms/BIND1/join", json={"handle": "bob"}).json()
    r = client.post(
        "/rooms/BIND1/submit",
        json={"text": "eve's private line"},
        headers={"X-Player-Token": eve["player_token"]},
    )
    assert r.status_code == 200
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        own = client.get(
            "/rooms/BIND1/snapshot",
            params={"role": "attacker"},
            headers={"X-Player-Token": eve["player_token"]},
        ).json()
        if own["turns"]:
            break
        time.sleep(0.05)
    assert [t["text"] for t in own["turns"]] == ["eve's private line"]
    # Bob with a query id, no token, or his own token: never eve's turns.
    for kwargs in (
        {"params": {"role": "attacker", "player_id": eve["player_id"]}},
        {"params": {"role": "attacker"}},
        {"params": {"role": "attacker"}, "headers": {"X-Player-Token": bob["player_token"]}},
    ):
        snap = client.get("/rooms/BIND1/snapshot", **kwargs).json()
        assert snap["turns"] == [] and snap["replies"] == [] and snap["myOutcomes"] == []
        ids = {p["identity"] for p in snap["players"]}
        assert eve["player_id"] not in ids
        assert all(lb["player"] in ("", bob["player_id"]) for lb in snap["leaderboard"])
    with client.websocket_connect(
        f"/ws?room=BIND1&role=attacker&player_token={eve['player_token']}"
    ) as ws:
        first = ws.receive_json()
        assert [t["text"] for t in first["snapshot"]["turns"]] == ["eve's private line"]
        assert first["snapshot"]["players"][0]["identity"] == eve["player_id"]
    with client.websocket_connect(
        f"/ws?room=BIND1&role=attacker&player_id={eve['player_id']}"
    ) as ws:
        assert ws.receive_json()["snapshot"]["turns"] == []
