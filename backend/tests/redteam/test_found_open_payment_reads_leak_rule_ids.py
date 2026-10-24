"""FOUND (open, final pass, tested at 48d821a): with OPS_TOKEN set, the read routes
`GET /payments`, `GET /payments/{id}` and `GET /audit` need no credential and return the full
bank-side record: decision rule ids, fingerprint, attestations, certificates (nonce redacted),
the audit history with refusal invariants, and every other room's payments.

The role-scoped WebSocket (0becb1b) exists so that attacker sockets never see payment or
attack events ("rule ids, fingerprints, refusals go to board and ops sockets only") and the
form turn path deliberately returns `public_outcome` without rule ids. The REST reads undo
both: the form path hands the player `payment_id`, and `GET /payments/{id}` then tells them
exactly which rule held them (H-01: switch rail to ACH; H-07: drop under $1,000; H-03: stay
under 3x baseline). `GET /payments` does not even need the id.

Scope: information only. No money moves (release needs the token and the nonce is redacted),
so I1..I7 hold. It defeats the stated attacker-view design and gives red-teamers the policy's
answer key.

Fix (for the lead, not applied here): put `deps.ops_guard` on the three GET routes (and
`/eval/results` if wanted) when OPS_TOKEN is set. The frontend's /ops and /board already hold
the token, but `frontend/src/lib/kernel/rest.ts` sends `opsHeaders()` only on writes today:
`kernel.payments`, `kernel.payment`, `kernel.audit` and `kernel.verify` need it too.

Asserts the SECURE behaviour, so it is RED today.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.redteam.conftest import OPS_TOKEN

HDR = {"X-Ops-Token": OPS_TOKEN}


def _held_payment(client: TestClient) -> str:
    r = client.post(
        "/payments",
        json={
            "account_id": "acc_margaret",
            "amount_cents": 50_000,
            "currency": "USD",
            "beneficiary": {"name": "X", "account_ref": "ext_fresh_rt", "is_new": True},
            "rail": "WIRE",
            "conversation_id": "rt-reads",
        },
    )
    assert r.status_code == 200 and r.json()["state"] == "HELD", r.text
    return str(r.json()["id"])


def _leaks(body: dict[str, Any]) -> list[str]:
    found = []
    if (body.get("decision") or {}).get("rule_ids"):
        found.append("rule_ids")
    for k in ("fingerprint", "certificates", "history", "last_refusal"):
        if k in body:
            found.append(k)
    return found


def test_payment_list_needs_the_token(ops_client: TestClient) -> None:
    _held_payment(ops_client)
    r = ops_client.get("/payments")
    assert r.status_code == 401, (
        f"GET /payments open: {r.status_code}, leaks {_leaks(r.json()['payments'][0])}"
    )
    assert ops_client.get("/payments", headers=HDR).status_code == 200


def test_payment_record_needs_the_token(ops_client: TestClient) -> None:
    pid = _held_payment(ops_client)
    r = ops_client.get(f"/payments/{pid}")
    assert r.status_code == 401, (
        f"GET /payments/{{id}} open: {r.status_code}, leaks {_leaks(r.json())}"
    )
    assert ops_client.get(f"/payments/{pid}", headers=HDR).status_code == 200


def test_audit_tail_needs_the_token(ops_client: TestClient) -> None:
    _held_payment(ops_client)
    r = ops_client.get("/audit")
    assert r.status_code == 401, f"GET /audit open: {r.status_code}, {len(r.json())} rows"
    assert ops_client.get("/audit", headers=HDR).status_code == 200
