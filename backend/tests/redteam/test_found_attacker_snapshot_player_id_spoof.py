"""FOUND (open, final pass, tested at 48d821a): the attacker view trusts a self-declared
`player_id`, and the attacker snapshot lists every player's identity, so any red-teamer can
read any other red-teamer's turns, Margaret's replies to them, and their stage/decision.

`RoomStore.snapshot(room, "attacker", player_id)` filters turns, replies and outcomes by
`player_id`, but the id arrives as a bare query parameter on `GET /rooms/{room}/snapshot`
and on `/ws?role=attacker&player_id=`; nothing ties it to the caller's `X-Player-Token`.
The same snapshot returns `players[].identity` for everyone in the room, so the ids are
not even secret. Steps: join the room, read `players`, re-request the snapshot (or reopen
the socket) with a rival's identity.

Scope: no payment data, rule ids or refusals leak (those are stripped for the attacker role
regardless of `player_id`), so no invariant I1..I7 is touched. It breaks the property the
first pass recorded in test_attacks_room.py ("the attacker snapshot never carries ... another
player's turns"): a player can copy a rival's working script mid-game and the SpacetimeDB
module does not have this problem because it keys on the caller's identity.

Fix (for the lead, not applied here): resolve the attacker's player id from
`X-Player-Token` (header on /snapshot, `player_token=` or the first message on /ws) and
ignore the query `player_id`; and drop `identity` from `players[]` in the attacker view
(the leaderboard already shows handles).

Asserts the SECURE behaviour, so it is RED today.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

ROOM = "SPOOF1"


def _join(client: TestClient, handle: str) -> tuple[str, str]:
    j = client.post(f"/rooms/{ROOM}/join", json={"handle": handle}).json()
    return str(j["player_id"]), str(j["player_token"])


def _wait_for_turn(client: TestClient, player_id: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snap = client.get(
            f"/rooms/{ROOM}/snapshot", params={"role": "attacker", "player_id": player_id}
        ).json()
        if snap["turns"]:
            return
        time.sleep(0.05)
    raise AssertionError("eve's turn never appeared")


def test_attacker_snapshot_does_not_list_other_players_identities(client: TestClient) -> None:
    eve_id, _ = _join(client, "eve")
    bob_id, _ = _join(client, "bob")
    snap = client.get(
        f"/rooms/{ROOM}/snapshot", params={"role": "attacker", "player_id": bob_id}
    ).json()
    identities = {p["identity"] for p in snap["players"]}
    # SECURE expectation: bob learns handles, never the ids that unlock other players' views.
    assert eve_id not in identities, f"attacker snapshot leaks rival identities: {identities}"


def test_spoofed_player_id_does_not_reveal_another_players_turns(client: TestClient) -> None:
    eve_id, eve_token = _join(client, "eve")
    _join(client, "bob")
    secret = "my secret working script line, do not share"
    r = client.post(
        f"/rooms/{ROOM}/submit", json={"text": secret}, headers={"X-Player-Token": eve_token}
    )
    assert r.status_code == 200, r.text
    _wait_for_turn(client, eve_id)

    # bob presents eve's identity (read from players[]) with no token at all.
    spoof = client.get(
        f"/rooms/{ROOM}/snapshot", params={"role": "attacker", "player_id": eve_id}
    ).json()
    texts = [t["text"] for t in spoof["turns"]]
    assert secret not in texts, f"PLAYER_ID SPOOF: rival's turns served to anyone: {texts}"
    assert spoof["replies"] == [] and spoof["myOutcomes"] == []

    # Same over the socket.
    with client.websocket_connect(f"/ws?room={ROOM}&role=attacker&player_id={eve_id}") as ws:
        first = ws.receive_json()
    assert first["type"] == "room"
    ws_texts = [t["text"] for t in first["snapshot"]["turns"]]
    assert secret not in ws_texts, f"PLAYER_ID SPOOF over /ws: {ws_texts}"
