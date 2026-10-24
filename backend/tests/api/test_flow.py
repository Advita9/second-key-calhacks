"""G2 end to end over HTTP: scenarios A, B, C, mutation, audit, demo gating, ops token."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api import deps
from tests.api.conftest import make_client

CASES = Path(__file__).resolve().parents[3] / "fixtures" / "cases"


def case(case_id: str) -> dict[str, Any]:
    raw = json.loads((CASES / f"{case_id}.json").read_text())
    assert isinstance(raw, dict)
    return raw


def scenario_a_body() -> dict[str, Any]:
    """S-03 payment and conversation with an EMPTY mule list (lead amendment 1)."""
    c = case("S-03")
    return {
        **c["payment"],
        "conversation_id": "conv_a",
        "conversation": c["conversation"],
        "account_context": {**c["account_context"], "mule_list": []},
    }


def scenario_b_body() -> dict[str, Any]:
    c = case("L-01")
    return {
        **c["payment"],
        "conversation_id": "conv_b",
        "conversation": c["conversation"],
        "account_context": c["account_context"],
    }


def create(client: TestClient, body: dict[str, Any], **headers: str) -> dict[str, Any]:
    r = client.post("/payments", json=body, headers=headers)
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def allow_and_certify(client: TestClient, **headers: str) -> tuple[str, dict[str, Any]]:
    p = create(client, scenario_b_body())
    assert p["decision"]["outcome"] == "ALLOW" and p["state"] == "ELIGIBLE_TO_SUBMIT"
    r = client.post(
        f"/payments/{p['id']}/certificate",
        json={"actor_id": "ops_1", "capability": "BANK_REVIEW"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    cert: dict[str, Any] = r.json()["certificate"]
    return p["id"], cert


# ---------------------------------------------------------------- scenario A


def test_scenario_a_irs_wire_is_held_with_evidence(client: TestClient) -> None:
    body = scenario_a_body()
    p = create(client, body)
    assert p["state"] == "HELD"
    assert p["decision"]["outcome"] == "HOLD"
    assert "H-01" in p["decision"]["rule_ids"]
    assert "D-01" not in p["decision"]["rule_ids"]
    ids = {e["id"] for e in body["conversation"]}
    signals = p["decision"]["signals"]
    assert signals, "expected at least one signal"
    assert any(s["source_id"] in ids for s in signals)
    for s in signals:
        text = next(e["text"] for e in body["conversation"] if e["id"] == s["source_id"])
        assert s["evidence_span"] in text
    assert len(p["fingerprint"]) == 64
    # The record is readable and carries history with the decision.
    rec = client.get(f"/payments/{p['id']}").json()
    assert rec["state"] == "HELD" and any(h["kind"] == "DECIDED" for h in rec["history"])


def test_co_approver_cannot_lift_hold_but_bank_review_can(client: TestClient) -> None:
    p = create(client, scenario_a_body())
    r = client.post(
        f"/payments/{p['id']}/attest", json={"actor_id": "ext_priya", "capability": "CO_APPROVER"}
    )
    assert r.status_code == 200 and r.json()["state"] == "HELD"
    r = client.post(
        f"/payments/{p['id']}/certificate", json={"actor_id": "ops_1", "capability": "BANK_REVIEW"}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NOT_ELIGIBLE"
    r = client.post(
        f"/payments/{p['id']}/attest", json={"actor_id": "ops_1", "capability": "BANK_REVIEW"}
    )
    assert r.status_code == 200 and r.json()["state"] == "ELIGIBLE_TO_SUBMIT"
    assert len(r.json()["attestations"]) == 2


# ---------------------------------------------------------------- scenario B


def test_scenario_b_known_biller_allow_release_submitted(client: TestClient) -> None:
    pid, cert = allow_and_certify(client)
    assert set(cert) >= {"id", "fingerprint", "policy_version", "nonce", "expires_at"}
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": cert["nonce"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "SUBMITTED"
    assert r.json()["nessie_transfer_id"]
    rec = client.get(f"/payments/{pid}").json()
    assert (
        rec["state"] == "SUBMITTED" and rec["nessie_transfer_id"] == r.json()["nessie_transfer_id"]
    )
    assert rec["certificates"][0]["nonce"] == "<redacted>"
    assert rec["certificates"][0]["consumed"] is True
    # I3: the same certificate is refused on replay.
    r2 = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": cert["nonce"]}
    )
    assert r2.status_code == 409
    assert r2.json() == {
        "refused": True,
        "invariant": "I3_REPLAY",
        "text": "SETTLEMENT REFUSED · I3_REPLAY",
    }
    assert client.get(f"/payments/{pid}").json()["last_refusal"] == "I3_REPLAY"


def test_release_with_wrong_nonce_is_refused(client: TestClient) -> None:
    pid, cert = allow_and_certify(client)
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": "0" * 32}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NO_CERT"
    assert client.get(f"/payments/{pid}").json()["state"] == "ELIGIBLE_TO_SUBMIT"


# ---------------------------------------------------------------- scenario C


def test_scenario_c_priya_cannot_attest_to_herself(client: TestClient) -> None:
    body = scenario_b_body()
    body["beneficiary"] = {"name": "Priya", "account_ref": "ext_priya", "is_new": False}
    body["amount_cents"] = 250_000
    p = create(client, body)
    r = client.post(
        f"/payments/{p['id']}/attest",
        json={"actor_id": "ext_priya", "capability": "CO_APPROVER", "note": "looks fine"},
    )
    assert r.status_code == 409
    assert r.json()["refused"] is True and r.json()["invariant"] == "I5_CONFLICT"
    assert client.get(f"/payments/{p['id']}").json()["attestations"] == []


# ---------------------------------------------------------------- I2 mutation


def test_mutate_after_certificate_voids_it(client: TestClient) -> None:
    pid, cert = allow_and_certify(client)
    r = client.post(f"/payments/{pid}/mutate", json={"amount_cents": 800_001})
    assert r.status_code == 200, r.text
    mutated = r.json()
    assert mutated["fingerprint"] != cert["fingerprint"]
    assert mutated["certificates"][0]["voided"] is True
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": cert["nonce"]}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I2_FINGERPRINT"
    assert client.get(f"/payments/{pid}").json()["state"] != "SUBMITTED"


def test_deny_cancels_and_voids(client: TestClient) -> None:
    pid, cert = allow_and_certify(client)
    r = client.post(f"/payments/{pid}/deny", json={"actor_id": "ops_1", "note": "looks wrong"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "CANCELLED"
    rec = client.get(f"/payments/{pid}").json()
    assert rec["state"] == "CANCELLED"
    assert rec["certificates"][0]["voided"] is True
    assert any(
        h["kind"] == "CANCELLED" and h["actor"] == "BANK_REVIEW:ops_1" for h in rec["history"]
    )
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": cert["nonce"]}
    )
    assert r.status_code == 409
    assert client.get(f"/payments/{pid}").json()["state"] == "CANCELLED"
    r = client.post(f"/payments/{pid}/deny", json={"actor_id": "ops_1"})
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NOT_ELIGIBLE"


def test_deny_on_denied_is_i6(client: TestClient) -> None:
    c = case("S-03")
    p = create(
        client, {**c["payment"], "conversation_id": "x", "account_context": c["account_context"]}
    )
    assert p["state"] == "DENIED"
    r = client.post(f"/payments/{p['id']}/deny", json={"actor_id": "ops_1"})
    assert r.status_code == 409 and r.json()["invariant"] == "I6_DENIED"
    r = client.post(
        f"/payments/{p['id']}/attest", json={"actor_id": "ops_1", "capability": "BANK_REVIEW"}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I6_DENIED"


# ---------------------------------------------------------------- audit (I7)


def test_audit_verify_then_tamper(client: TestClient) -> None:
    create(client, scenario_b_body())
    v = client.get("/audit/verify").json()
    assert v["ok"] is True and v["length"] >= 3
    events = client.get("/audit?limit=200").json()
    assert isinstance(events, list) and events[0]["seq"] == 1
    assert set(events[0]) >= {"seq", "ts", "actor", "kind", "payload", "prev_hash", "hash"}
    t = client.post("/audit/tamper")
    assert t.status_code == 200, t.text
    v2 = client.get("/audit/verify").json()
    assert v2["ok"] is False
    assert v2["first_bad_seq"] == t.json()["tampered_seq"]


# ---------------------------------------------------------------- gating


def test_mutate_and_tamper_404_when_demo_off(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(monkeypatch, DEMO_MODE="0") as c:
        pid, _ = allow_and_certify(c)
        assert c.post(f"/payments/{pid}/mutate", json={"amount_cents": 1}).status_code == 404
        assert c.post("/audit/tamper").status_code == 404
        assert c.get(f"/payments/{pid}").json()["state"] == "ELIGIBLE_TO_SUBMIT"
    deps.reset()


def test_ops_token_required_when_set(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    tok = "ops-secret-123"
    with make_client(monkeypatch, OPS_TOKEN=tok) as c:
        p = create(c, scenario_a_body(), **{"X-Ops-Token": tok})
        attest = f"/payments/{p['id']}/attest"
        # BANK_REVIEW without the header: 401 and nothing changes.
        r = c.post(attest, json={"actor_id": "ops_1", "capability": "BANK_REVIEW"})
        assert r.status_code == 401 and r.json() == {
            "refused": True,
            "reason": "ops token required",
        }
        assert c.get(f"/payments/{p['id']}").json()["state"] == "HELD"
        # Wrong header: still 401.
        r = c.post(
            attest,
            json={"actor_id": "ops_1", "capability": "BANK_REVIEW"},
            headers={"X-Ops-Token": "nope"},
        )
        assert r.status_code == 401
        # CUSTOMER_CHECKIN never needs it.
        r = c.post(attest, json={"actor_id": "margaret", "capability": "CUSTOMER_CHECKIN"})
        assert r.status_code == 200 and r.json()["state"] == "HELD"
        # With the header: hold lifted.
        r = c.post(
            attest,
            json={"actor_id": "ops_1", "capability": "BANK_REVIEW"},
            headers={"X-Ops-Token": tok},
        )
        assert r.status_code == 200 and r.json()["state"] == "ELIGIBLE_TO_SUBMIT"
        for path in (
            f"/payments/{p['id']}/certificate",
            f"/payments/{p['id']}/release",
            f"/payments/{p['id']}/mutate",
            f"/payments/{p['id']}/deny",
            "/audit/tamper",
            "/rooms/DEMO/reset",
        ):
            body = {
                "actor_id": "x",
                "capability": "BANK_REVIEW",
                "certificate_id": "c",
                "nonce": "n",
            }
            assert c.post(path, json=body).status_code == 401, path
        assert c.get("/health").json()["ops_token"] == "set"
    deps.reset()


def test_unknown_payment_404_and_bad_body_422(client: TestClient) -> None:
    assert client.get("/payments/pay_nope").status_code == 404
    r = client.post("/payments", json={"amount_cents": -5, "beneficiary": {}, "rail": "WIRE"})
    assert r.status_code == 422
    r = client.post("/payments", json={**scenario_b_body(), "rail": "CARRIER_PIGEON"})
    assert r.status_code == 400


def test_list_payments_newest_first(client: TestClient) -> None:
    a = create(client, scenario_a_body())["id"]
    b = create(client, scenario_b_body())["id"]
    ids = [p["id"] for p in client.get("/payments").json()["payments"]]
    assert ids[:2] == [b, a]


def test_post_payments_account_context_requires_ops_token_when_set(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tok = "ops-secret-456"
    with make_client(monkeypatch, OPS_TOKEN=tok) as c:
        # A caller-supplied context (empty mule list) or transcript steers the decision.
        r = c.post("/payments", json=scenario_a_body())
        assert r.status_code == 401 and r.json()["refused"] is True
        body = scenario_b_body()
        body.pop("account_context")
        r = c.post("/payments", json=body)  # conversation alone also needs the token
        assert r.status_code == 401
        body.pop("conversation")
        r = c.post("/payments", json=body)  # plain api.md body: open, default context
        assert r.status_code == 200 and r.json()["decision"]["outcome"] == "ALLOW"
        r = c.post("/payments", json=scenario_a_body(), headers={"X-Ops-Token": tok})
        assert r.status_code == 200 and r.json()["state"] == "HELD"
        assert c.get("/payments").json()["payments"][0]["id"] == r.json()["id"]
    deps.reset()


def test_unknown_payment_is_404_on_every_route(client: TestClient) -> None:
    body = {"actor_id": "x", "capability": "CUSTOMER_CHECKIN", "certificate_id": "c", "nonce": "n"}
    for path in ("attest", "certificate", "release", "mutate", "deny"):
        r = client.post(f"/payments/pay_nope/{path}", json={**body, "amount_cents": 5})
        assert r.status_code == 404, (path, r.text)
        assert r.json() == {"error": "payment not found", "key": "pay_nope"}


def test_huge_or_bad_amounts_are_422_and_never_submit(client: TestClient) -> None:
    for amt in (2**63, 2**64, 10**13, 0, -1, 1.5, "1e9"):
        r = client.post("/payments", json={**scenario_b_body(), "amount_cents": amt})
        assert r.status_code == 422, (amt, r.status_code)
    assert client.get("/payments").json()["payments"] == []
    pid, _ = allow_and_certify(client)
    r = client.post(f"/payments/{pid}/mutate", json={"amount_cents": 2**63})
    assert r.status_code == 422
    assert client.get(f"/payments/{pid}").json()["amount_cents"] == 800_000
