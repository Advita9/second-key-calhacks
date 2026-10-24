"""FOUND (open, final pass, tested at 48d821a): both turn rate limits are keyed on an identity
the caller chooses, so an unauthenticated client drives Margaret (and, in real mode, Claude,
STT and TTS) as fast as it can post.

1. Form path `POST /rooms/{room}/turns` (push-to-talk, no credential): `TurnRateLimiter`
   keys on `(room, player_id)` and `player_id` is a form field defaulting to "player".
   Posting with `player_id=rot0, rot1, rot2 ...` gets 200, 200, 200 in the same second.
2. Memory-room path `POST /rooms/{room}/submit`: the store limits one turn per 3 s per
   player, but `POST /rooms/{room}/join` is unlimited and mints a fresh identity and token
   each time. Join five times, submit five turns at once: five 200s, five Margaret turns.

Scope: no money and no payment state (every turn still goes through the same policy), so no
invariant is touched. The cost is the real-mode budget: each turn is one Margaret model
call plus TTS, and `hub.tokens` and the player table grow without bound. docs/api.md promises
"One form turn per player_id per 3 s", which is true and useless when the id is free.

Fix (for the lead, not applied here): key the form limiter on the client address (or a
per-room global budget such as 1 turn/s), and rate-limit `/join` per address as well.

Asserts the SECURE behaviour, so it is RED today.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_form_turn_limit_survives_a_rotating_player_id(client: TestClient) -> None:
    codes = [
        client.post(
            "/rooms/ROTATE1/turns", data={"text": "hello dear", "player_id": f"rot{i}"}
        ).status_code
        for i in range(5)
    ]
    # SECURE expectation: five unauthenticated turns inside one second from one client must
    # not all be served.
    assert 429 in codes, f"form rate limit bypassed by rotating player_id: {codes}"


def test_submit_limit_survives_a_join_flood(client: TestClient) -> None:
    tokens = [
        client.post("/rooms/FLOOD1/join", json={"handle": f"h{i}"}).json()["player_token"]
        for i in range(5)
    ]
    codes = [
        client.post(
            "/rooms/FLOOD1/submit", json={"text": "hello dear"}, headers={"X-Player-Token": t}
        ).status_code
        for t in tokens
    ]
    assert 429 in codes, f"submit rate limit bypassed by re-joining: {codes}"
