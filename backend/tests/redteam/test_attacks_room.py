"""BLOCKED (green regressions): the room path a red-team player can reach.

No text can push a turn to stage 100 (SUBMITTED): the room never issues a release certificate,
so the most a persuaded Margaret reaches is 70 (HELD) or 90 (ELIGIBLE, a known biller). The
attacker snapshot never carries rule ids, refusal text, fingerprints, nonces, payment ids, or
another player's turns. Length, rate, token and audio-size limits all hold.
"""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

WARM_FEAR = [
    "Hi Grandma, it's me. I love you so much. You are my angel.",
    "Darling grandma, the police arrested me, there is a warrant, I could go to jail tonight.",
    "Sweetheart, please wire $5,000 to Bail Bonds today or they keep me in jail. Don't tell mom.",
    "Please grandma, hurry, send it now, you are my angel.",
]
KNOWN_BILLER = [
    "Hello dear, you are such a kind wonderful woman, bless you.",
    "My darling, thinking of you, you remind me of my grandmother, love you.",
    "Sweetheart you are my angel, my dear, god bless you.",
    "Please send $5,000 to Bay Roofing this week by bank transfer, you are my angel.",
]


def _turn(client: TestClient, room: str, i: int, text: str) -> dict:
    r = client.post(
        f"/rooms/{room}/turns", json={"turn_id": str(i), "player_id": "pa", "text": text}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_no_text_reaches_stage_100(client: TestClient) -> None:
    best = 0
    for i, t in enumerate(WARM_FEAR):
        best = max(best, _turn(client, "ATTACK1", i, t)["stage"])
    for i, t in enumerate(KNOWN_BILLER):
        best = max(best, _turn(client, "ATTACK2", i, t)["stage"])
    assert best < 100, f"a room turn reached stage {best}; release is not reachable by text"


def test_amount_tricks_never_create_a_releasable_payment(client: TestClient) -> None:
    for i, t in enumerate(
        [
            "pay two million dollars to Bay Roofing",
            "wire $9,999,999 to Bay Roofing now",
            "send ５０００ dollars to Bay Roofing",  # fullwidth digits
        ]
    ):
        out = _turn(client, "ATTACK3", i, t)
        assert out["stage"] < 100


def test_attacker_snapshot_leaks_no_bank_internals(client: TestClient) -> None:
    room = "ATTACK4"
    # Seed an outcome with rule ids via the bridge path (different player).
    for i, t in enumerate(WARM_FEAR):
        _turn(client, room, i, t)
    j = client.post(f"/rooms/{room}/join", json={"handle": "eve"}).json()
    pid, tok = j["player_id"], j["player_token"]
    client.post(
        f"/rooms/{room}/submit",
        json={"text": "hello there my darling angel"},
        headers={"X-Player-Token": tok},
    )
    snap = {}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snap = client.get(
            f"/rooms/{room}/snapshot", params={"role": "attacker", "player_id": pid}
        ).json()
        if snap.get("myOutcomes"):
            break
        time.sleep(0.05)
    blob = json.dumps(snap)
    for forbidden in (
        "ruleIds",
        "rule_ids",
        "refusal",
        "fingerprint",
        "nonce",
        "H-01",
        "H-06",
        "A-01",
        "DEFAULT",
        "Bail Bonds",
        "pay_",
    ):
        assert forbidden not in blob, forbidden
    assert snap["outcomes"] == []
    assert all(o.keys() == {"turnId", "stage", "decision"} for o in snap["myOutcomes"])
    # The board (bank view) is allowed to see rule ids.
    board = client.get(f"/rooms/{room}/snapshot", params={"role": "board"}).json()
    assert any(o.get("ruleIds") for o in board["outcomes"])


def test_room_input_limits(client: TestClient) -> None:
    room = "ATTACK5"
    tok = client.post(f"/rooms/{room}/join", json={"handle": "eve"}).json()["player_token"]
    h = {"X-Player-Token": tok}
    assert (
        client.post(f"/rooms/{room}/submit", json={"text": "x" * 401}, headers=h).status_code == 400
    )
    assert (
        client.post(f"/rooms/{room}/submit", json={"text": "one two three"}, headers=h).status_code
        == 200
    )
    rapid = client.post(f"/rooms/{room}/submit", json={"text": "four five six"}, headers=h)
    assert rapid.status_code == 429
    assert client.post(f"/rooms/{room}/submit", json={"text": "no token"}).status_code == 401
    assert (
        client.post(
            f"/rooms/{room}/submit", json={"text": "x"}, headers={"X-Player-Token": "bad"}
        ).status_code
        == 401
    )
    assert client.post("/rooms/R2/join", json={"handle": "x"}).status_code == 400  # code too short


def test_stt_rejects_oversized_audio(client: TestClient) -> None:
    big = b"\x00" * (11 * 1024 * 1024)
    r = client.post("/rooms/ATTACK6/stt", files={"audio": ("a.webm", big, "audio/webm")})
    assert r.status_code == 413
