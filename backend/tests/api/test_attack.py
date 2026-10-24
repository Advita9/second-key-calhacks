"""All four attack panel routes refuse with the right invariant."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import deps
from tests.api.conftest import make_client

ATTACKS = ("inject", "mutate", "replay", "self-approve")


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


def test_attack_routes_require_ops_token_when_set(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tok = "ops-secret-789"
    with make_client(monkeypatch, OPS_TOKEN=tok) as c:
        for name in ATTACKS:
            r = c.post(f"/attack/{name}")
            assert r.status_code == 401, name
            assert r.json() == {"refused": True, "reason": "ops token required"}
        assert c.get("/payments").json()["payments"] == []  # nothing was created
        assert c.get("/audit/verify").json()["length"] == 0
        for name in ATTACKS:
            r = c.post(f"/attack/{name}", headers={"X-Ops-Token": tok})
            assert r.status_code == 200 and r.json()["refused"] is True, name
    deps.reset()


def test_attack_mutate_404_when_demo_off(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(monkeypatch, DEMO_MODE="0") as c:
        assert c.post("/attack/mutate").status_code == 404
        assert c.get("/payments").json()["payments"] == []
        for name in ("inject", "replay", "self-approve"):
            assert c.post(f"/attack/{name}").status_code == 200, name
    deps.reset()


def test_attacks_leave_nothing_eligible(client: TestClient) -> None:
    for name in ATTACKS:
        body = _run(client, name)
        steps = body["steps"]
        assert isinstance(steps, list)
        if name in ("mutate", "self-approve"):
            assert any(step.startswith("cleanup:") for step in steps), name
    states = [p["state"] for p in client.get("/payments").json()["payments"]]
    assert states, "attacks create payments"
    assert not {"ELIGIBLE_TO_SUBMIT", "HELD", "PENDING_REVIEW", "DRAFT"} & set(states), states
    assert set(states) <= {"SUBMITTED", "CANCELLED"}
    for p in client.get("/payments").json()["payments"]:
        if p["state"] == "CANCELLED":
            assert all(c["voided"] for c in p["certificates"])
            assert all(a["voided"] for a in p["attestations"])
