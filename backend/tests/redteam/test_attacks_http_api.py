"""BLOCKED (green regressions): HTTP surface. Ops-token gating, body tricks, release refusals,
audio path traversal, the attack panel, semantic dodges.

Runs over a TestClient so it is CI-safe (no external server). The same attacks were also run by
hand against the manually started port 8020.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.redteam.conftest import OPS_TOKEN

BASE: dict[str, Any] = {
    "account_id": "acc_margaret",
    "currency": "USD",
    "beneficiary": {"name": "X", "account_ref": "ext_fresh", "is_new": True},
    "rail": "WIRE",
    "conversation_id": "t",
}
CTX = {
    "baseline_90d_cents": 300_000,
    "known_billers": ["PG&E", "Bay Roofing"],
    "prior_payees": ["ext_bay_roofing", "ext_pge"],
    "mule_list": ["ext_9f31"],
}
HDR = {"X-Ops-Token": OPS_TOKEN}


def _held(client: TestClient, headers: dict[str, str] | None = None) -> str:
    # Supplying a custom account_context is itself ops-gated when a token is set, so the setup
    # create carries the header; the point of these tests is the follow-on routes.
    body = {
        **BASE,
        "amount_cents": 1_850_000,
        "beneficiary": {"name": "Agent", "account_ref": "ext_new_mule", "is_new": True},
        "account_context": {**CTX, "mule_list": []},
    }
    r = client.post("/payments", json=body, headers=headers or {})
    assert r.status_code == 200 and r.json()["state"] == "HELD", r.text
    pid: str = r.json()["id"]
    return pid


# ---------------------------------------------------------------- ops token


def test_create_with_attacker_context_needs_the_token(ops_client: TestClient) -> None:
    """A caller-supplied account_context or transcript could steer the decision, so with a token
    configured it is an operator privilege. Without the header it is refused; the attacker cannot
    inject a favourable context (empty mule list, huge baseline) to dodge the rules."""
    body = {
        **BASE,
        "amount_cents": 50_000,
        "beneficiary": {"name": "X", "account_ref": "ext_9f31", "is_new": True},
        "account_context": {**CTX, "mule_list": []},  # attacker clears the mule list
    }
    no_header = ops_client.post("/payments", json=body)
    assert no_header.status_code == 401
    assert no_header.json() == {"refused": True, "reason": "ops token required"}
    # Without a custom context the default (real) context is used and create is open.
    plain = ops_client.post(
        "/payments",
        json={
            **BASE,
            "amount_cents": 50_000,
            "beneficiary": {"name": "X", "account_ref": "ext_9f31", "is_new": True},
        },
    )
    assert plain.status_code == 200
    # With the header the operator may supply a context.
    assert ops_client.post("/payments", json=body, headers=HDR).status_code == 200


def test_operator_routes_need_the_token(ops_client: TestClient) -> None:
    pid = _held(ops_client, headers=HDR)
    routes = [
        (f"/payments/{pid}/attest", {"actor_id": "ops", "capability": "BANK_REVIEW"}),
        (f"/payments/{pid}/certificate", {"actor_id": "ops", "capability": "BANK_REVIEW"}),
        (f"/payments/{pid}/release", {"certificate_id": "c", "nonce": "n"}),
        (f"/payments/{pid}/mutate", {"amount_cents": 1}),
        (f"/payments/{pid}/deny", {"actor_id": "ops"}),
        ("/audit/tamper", {}),
        ("/rooms/DEMO/reset", {}),
    ]
    for path, body in routes:
        missing = ops_client.post(path, json=body)
        assert missing.status_code == 401, path
        assert missing.json() == {"refused": True, "reason": "ops token required"}
        wrong = ops_client.post(path, json=body, headers={"X-Ops-Token": "nope"})
        assert wrong.status_code == 401, path
    # Nothing changed state.
    assert ops_client.get(f"/payments/{pid}").json()["state"] == "HELD"


def test_customer_checkin_never_needs_the_token(ops_client: TestClient) -> None:
    pid = _held(ops_client, headers=HDR)
    r = ops_client.post(
        f"/payments/{pid}/attest", json={"actor_id": "margaret", "capability": "CUSTOMER_CHECKIN"}
    )
    assert r.status_code == 200 and r.json()["state"] == "HELD"


def test_right_token_lifts_hold(ops_client: TestClient) -> None:
    pid = _held(ops_client, headers=HDR)
    r = ops_client.post(
        f"/payments/{pid}/attest",
        json={"actor_id": "ops", "capability": "BANK_REVIEW"},
        headers=HDR,
    )
    assert r.status_code == 200 and r.json()["state"] == "ELIGIBLE_TO_SUBMIT"


# ---------------------------------------------------------------- body tricks


def test_amount_zero_negative_float_are_422(client: TestClient) -> None:
    for amt in (0, -5, 1.5):
        r = client.post("/payments", json={**BASE, "amount_cents": amt})
        assert r.status_code == 422, amt


def test_huge_amount_never_submits(client: TestClient) -> None:
    # Beyond SQLite's INTEGER range (2**63) the insert raises OverflowError. The transaction
    # rolls back: no payment is created, nothing submits. On a live server this surfaces as a
    # 500 (a robustness nit worth fixing) but it fails closed; TestClient re-raises it.
    try:
        r = client.post("/payments", json={**BASE, "amount_cents": 2**63})
    except OverflowError:
        return  # fail-closed: the write was rejected, no payment row exists
    assert r.status_code >= 400
    assert "SUBMITTED" not in r.text


def test_bogus_rail_is_400(client: TestClient) -> None:
    r = client.post("/payments", json={**BASE, "amount_cents": 100_000, "rail": "CARRIER_PIGEON"})
    assert r.status_code == 400


def test_extra_fields_are_ignored_not_trusted(client: TestClient) -> None:
    r = client.post(
        "/payments",
        json={
            **BASE,
            "amount_cents": 100_000,
            "is_admin": True,
            "stage": 100,
            "state": "SUBMITTED",
            "account_context": {**CTX, "mule_list": []},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] in ("HELD", "PENDING_REVIEW")  # not SUBMITTED
    assert body["state"] != "SUBMITTED"


def test_semantic_dodges_never_allow(client: TestClient) -> None:
    # PG&E display name with a fresh ref on ACH: known-biller ALLOW is by ref only -> not ALLOW.
    r = client.post(
        "/payments",
        json={
            **BASE,
            "amount_cents": 50_000,
            "rail": "ACH",
            "beneficiary": {"name": "PG&E", "account_ref": "ext_pge_fake", "is_new": True},
            "account_context": CTX,
        },
    )
    assert r.json()["decision"]["outcome"] != "ALLOW"

    # is_new:false injected for a never-seen ref on WIRE: is_new is recomputed -> H-01 HOLD.
    r = client.post(
        "/payments",
        json={
            **BASE,
            "amount_cents": 50_000,
            "rail": "WIRE",
            "beneficiary": {"name": "X", "account_ref": "ext_never_seen", "is_new": False},
            "account_context": CTX,
        },
    )
    d = r.json()["decision"]
    assert d["outcome"] == "HOLD" and "H-01" in d["rule_ids"]


def test_mule_ref_denies_exact_and_lookalike_is_not_allowed(client: TestClient) -> None:
    exact = client.post(
        "/payments",
        json={
            **BASE,
            "amount_cents": 50_000,
            "beneficiary": {"name": "X", "account_ref": "ext_9f31", "is_new": True},
            "account_context": CTX,
        },
    )
    assert exact.json()["decision"]["outcome"] == "DENY"
    # When found, a look-alike ref dodged the D-01 hard-deny (HELD by H-01 instead). Since
    # 02405d8 refs are normalized (NFKC, strip, casefold), so the look-alike IS the mule: DENY.
    look = client.post(
        "/payments",
        json={
            **BASE,
            "amount_cents": 50_000,
            "beneficiary": {"name": "X", "account_ref": "ext_9f31 ", "is_new": True},
            "account_context": CTX,
        },
    )
    assert look.json()["decision"]["outcome"] == "DENY"
    assert look.json()["state"] == "DENIED"


# ---------------------------------------------------------------- release over HTTP


def _allow_and_cert(client: TestClient) -> tuple[str, dict[str, Any]]:
    body = {
        **BASE,
        "amount_cents": 50_000,
        "rail": "ACH",
        "beneficiary": {"name": "Bay Roofing", "account_ref": "ext_bay_roofing", "is_new": False},
        "account_context": CTX,
    }
    pid = client.post("/payments", json=body).json()["id"]
    cert = client.post(
        f"/payments/{pid}/certificate", json={"actor_id": "ops", "capability": "BANK_REVIEW"}
    ).json()["certificate"]
    return pid, cert


def test_release_refusals_over_http(client: TestClient) -> None:
    pid, cert = _allow_and_cert(client)
    other, _ = _allow_and_cert(client)
    # cross-payment
    r = client.post(
        f"/payments/{other}/release", json={"certificate_id": cert["id"], "nonce": cert["nonce"]}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NO_CERT"
    # forged id
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": "cert_x", "nonce": cert["nonce"]}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NO_CERT"
    # wrong nonce
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": "0" * 32}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I1_NO_CERT"
    # mutate 1 cent then release old cert
    client.post(f"/payments/{pid}/mutate", json={"amount_cents": 50_001})
    r = client.post(
        f"/payments/{pid}/release", json={"certificate_id": cert["id"], "nonce": cert["nonce"]}
    )
    assert r.status_code == 409 and r.json()["invariant"] == "I2_FINGERPRINT"


# ---------------------------------------------------------------- audio + attack panel


def test_audio_path_traversal_is_404(client: TestClient) -> None:
    for path in (
        "/audio/..%2f..%2f..%2fetc%2fpasswd.wav",
        "/audio/%2e%2e%2fsecond_key.db.wav",
        "/audio/not_hex.wav",
        "/audio/" + "a" * 64 + ".wav",  # well-formed key, no such file
    ):
        assert client.get(path).status_code == 404, path


def test_attack_panel_all_refuse(client: TestClient) -> None:
    for name, invariant in [
        ("inject", None),
        ("mutate", "I2_FINGERPRINT"),
        ("replay", "I3_REPLAY"),
        ("self-approve", "I5_CONFLICT"),
    ]:
        r = client.post(f"/attack/{name}")
        assert r.status_code == 200, (name, r.text)
        body = r.json()
        assert body["refused"] is True, name
        if invariant is not None:
            assert body["invariant"] == invariant, name
