"""All four attack panel routes refuse with the right invariant."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _run(client: TestClient, name: str) -> dict[str, object]:
    r = client.post(f"/attack/{name}")
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    assert body["refused"] is True
    assert isinstance(body["steps"], list) and len(body["steps"]) >= 2
    assert isinstance(body["text"], str) and body["text"]
    return body


def test_inject_holds_on_facts_despite_no_concerns(client: TestClient) -> None:
    body = _run(client, "inject")
    assert body["invariant"] == "POLICY_HOLD"
    assert body["decision"] == "HOLD"
    rules = body["rule_ids"]
    assert isinstance(rules, list) and "H-01" in rules and "H-03" in rules
    assert "D-01" not in rules
    assert "H-02" not in rules  # the compromised signals are all zero
    assert str(body["text"]).startswith("HELD · ")
    assert "no concerns" in str(body["text"])


def test_mutate_is_i2(client: TestClient) -> None:
    body = _run(client, "mutate")
    assert body["invariant"] == "I2_FINGERPRINT"
    assert body["text"] == "SETTLEMENT REFUSED · I2_FINGERPRINT"


def test_replay_is_i3(client: TestClient) -> None:
    body = _run(client, "replay")
    assert body["invariant"] == "I3_REPLAY"
    steps = body["steps"]
    assert isinstance(steps, list) and any("SUBMITTED" in s for s in steps)


def test_self_approve_is_i5(client: TestClient) -> None:
    body = _run(client, "self-approve")
    assert body["invariant"] == "I5_CONFLICT"


def test_attacks_leave_the_chain_intact(client: TestClient) -> None:
    for name in ("inject", "mutate", "replay", "self-approve"):
        _run(client, name)
    assert client.get("/audit/verify").json()["ok"] is True
