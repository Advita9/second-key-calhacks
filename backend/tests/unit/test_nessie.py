"""NessieClient, MockNessieTransport and NessieRail. No network: the mock transport only."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from kernel.clock import FakeClock
from kernel.models import Capability, State
from kernel.nessie import (
    MARGARET_ACCOUNT_REF,
    MOCK_KEY,
    MockNessieTransport,
    NessieClient,
    NessieRail,
    build_rail,
    created_id,
    dollars,
)
from kernel.policy.engine import V1_PATH, load_policy
from kernel.rail import RailError
from kernel.service import Kernel
from tests.factories import account_context, payment_in


def _client(transport: MockNessieTransport, key: str = MOCK_KEY) -> NessieClient:
    return NessieClient(key=key, transport=transport)


def _rail(transport: MockNessieTransport, cache: Path | None = None) -> NessieRail:
    return NessieRail(
        _client(transport),
        payee_accounts={MARGARET_ACCOUNT_REF: MARGARET_ACCOUNT_REF},
        cache_path=cache,
    )


def _kernel(rail: NessieRail, clock: FakeClock) -> Kernel:
    return Kernel(":memory:", policy=load_policy(V1_PATH), clock=clock, rail=rail)


def test_created_id_shapes() -> None:
    assert created_id({"code": 201, "objectCreated": {"_id": "abc"}}) == "abc"
    assert created_id({"_id": "x"}) == "x"
    assert created_id({"id": "y"}) == "y"
    with pytest.raises(RailError):
        created_id({"code": 201, "message": "no id"})
    with pytest.raises(RailError):
        created_id("nope")


def test_dollars_integer_floor_min_one() -> None:
    assert dollars(800_000) == 8000
    assert dollars(1234) == 12
    assert dollars(50) == 1


def test_mock_transport_shapes() -> None:
    t = MockNessieTransport()
    c = _client(t)
    acc = c.get_account(MARGARET_ACCOUNT_REF)
    assert acc["_id"] == MARGARET_ACCOUNT_REF and acc["balance"] == 24_000
    cid = c.create_customer("Bay", "Roofing")
    aid = c.create_account(cid, "ext_bay_roofing", 0)
    assert cid.startswith("cust_") and aid.startswith("acc_")
    wid = c.withdraw(MARGARET_ACCOUNT_REF, 12, "second-key pay_x 1234c")
    did = c.deposit(aid, 12, "second-key pay_x 1234c")
    assert wid.startswith("wd_") and did.startswith("dp_")
    kinds = [row["kind"] for row in t.ledger]
    assert kinds == ["withdrawal", "deposit"]
    assert t.ledger[0]["amount"] == 12 and t.ledger[0]["description"] == "second-key pay_x 1234c"
    # Balances never move in the sandbox; the mock mirrors that.
    assert c.get_account(MARGARET_ACCOUNT_REF)["balance"] == 24_000


def test_mock_transport_404_and_401() -> None:
    t = MockNessieTransport()
    with pytest.raises(RailError, match="404"):
        _client(t).get_account("acc_missing")
    with pytest.raises(RailError, match="401"):
        _client(t, key="wrong").get_account(MARGARET_ACCOUNT_REF)


def test_mock_transport_rejects_missing_fields() -> None:
    t = MockNessieTransport()
    r = httpx.Client(transport=t, base_url="https://mock").post(
        f"/accounts/{MARGARET_ACCOUNT_REF}/withdrawals?key={MOCK_KEY}", json={"amount": 1}
    )
    assert r.status_code == 400 and r.json()["code"] == 400


def test_rail_submit_withdraws_and_deposits(tmp_path: Path, clock: FakeClock) -> None:
    t = MockNessieTransport()
    rail = _rail(t, tmp_path / "nessie_payees.json")
    k = _kernel(rail, clock)
    p, d = k.create_payment(payment_in(), account_context(baseline_90d_cents=300_000))
    assert p.state is State.ELIGIBLE_TO_SUBMIT, d
    cert = k.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    out = k.release(p.id, cert.id, cert.nonce)
    assert out.state is State.SUBMITTED
    assert out.nessie_transfer_id is not None and out.nessie_transfer_id.startswith("wd_")
    wd, dp = t.ledger[-2], t.ledger[-1]
    assert wd["kind"] == "withdrawal" and wd["account"] == MARGARET_ACCOUNT_REF
    assert dp["kind"] == "deposit" and dp["account"] != MARGARET_ACCOUNT_REF
    assert wd["amount"] == dp["amount"] == 8000
    assert wd["description"] == f"second-key {p.id} 800000c"
    assert isinstance(wd["amount"], int)
    # Payee customer and account were created lazily and cached on disk.
    cache = json.loads((tmp_path / "nessie_payees.json").read_text())
    assert cache["accounts"]["ext_bay_roofing"] == dp["account"]
    assert "ext_bay_roofing" in cache["customers"]


def test_rail_reuses_cached_payee(tmp_path: Path) -> None:
    t = MockNessieTransport()
    cache = tmp_path / "c.json"
    rail = _rail(t, cache)
    a1 = rail.account_for("ext_bay_roofing")
    a2 = rail.account_for("ext_bay_roofing")
    assert a1 == a2 and len(t.customers) == 1
    rail2 = _rail(t, cache)
    assert rail2.account_for("ext_bay_roofing") == a1 and len(t.customers) == 1


def test_rail_rejects_bad_account_ref() -> None:
    rail = _rail(MockNessieTransport())
    with pytest.raises(RailError):
        rail.account_for("ext_../x")


def test_bad_key_is_rail_error() -> None:
    rail = NessieRail(_client(MockNessieTransport(), key="bad"))
    with pytest.raises(RailError, match="401"):
        rail.account_for("ext_bay_roofing")


def test_rail_failure_inside_release_leaves_payment_unsubmitted(clock: FakeClock) -> None:
    """I1: the rail raising rolls the release back; the certificate is not consumed."""
    t = MockNessieTransport()
    rail = _rail(t)
    k = _kernel(rail, clock)
    p, _ = k.create_payment(payment_in(), account_context(baseline_90d_cents=300_000))
    cert = k.issue_certificate(p.id, "ops_1", Capability.BANK_REVIEW)
    t.fail_with = 500
    with pytest.raises(RailError):
        k.release(p.id, cert.id, cert.nonce)
    rec = k.get(p.id)
    assert rec.payment.state is State.ELIGIBLE_TO_SUBMIT
    assert rec.payment.nessie_transfer_id is None
    assert rec.certificates[0].consumed_at is None
    assert not [row for row in t.ledger if row["kind"] == "deposit"]
    # A retry after the rail recovers succeeds with the same certificate.
    out = k.release(p.id, cert.id, cert.nonce)
    assert out.state is State.SUBMITTED


def test_build_rail_modes() -> None:
    rail, mode = build_rail({})
    assert mode == "mock" and isinstance(rail, NessieRail)
    assert rail.account_for(MARGARET_ACCOUNT_REF) == MARGARET_ACCOUNT_REF
    rail2, mode2 = build_rail(
        {"NESSIE_API_KEY": "k", "NESSIE_BASE_URL": "http://api.nessieisreal.com"}
    )
    assert mode2 == "real"
    assert str(rail2.client._http.base_url).startswith("https://")


def test_deposit_retries_with_type_on_400() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "type" not in body:
            return httpx.Response(400, json={"code": 400, "message": "type required"})
        return httpx.Response(201, json={"code": 201, "objectCreated": {"_id": "dp_1"}})

    c = NessieClient(key="k", transport=httpx.MockTransport(handler))
    assert c.deposit("acc", 5, "d") == "dp_1"
    assert len(calls) == 2 and calls[1]["type"] == "deposit"


# ---------------------------------------------------------------- recorded sandbox shapes

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "nessie"


@pytest.mark.parametrize("name", ["create_customer", "create_account", "withdrawal", "deposit"])
def test_recorded_create_shapes_yield_ids(name: str) -> None:
    rec = json.loads((RECORDED / f"{name}.json").read_text())
    assert rec["status"] == 201
    assert "<KEY>" in rec["url"] and "key=<KEY>" in rec["url"]
    body = rec["response"]
    assert body["code"] == 201 and "objectCreated" in body
    assert created_id(body) == body["objectCreated"]["_id"]


def test_recorded_get_account_shape_matches_client() -> None:
    rec = json.loads((RECORDED / "get_account.json").read_text())
    assert rec["status"] == 200

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rec["response"])

    c = NessieClient(key="k", transport=httpx.MockTransport(handler))
    acc = c.get_account("any")
    assert acc["_id"] == rec["response"]["_id"] and isinstance(acc["balance"], int)


def test_recorded_withdrawal_body_is_integer_dollars() -> None:
    rec = json.loads((RECORDED / "withdrawal.json").read_text())
    req = rec["request_body"]
    assert req["amount"] == 1 and isinstance(req["amount"], int)
    assert req["medium"] == "balance" and req["status"] == "completed"
    assert req["description"].startswith("second-key ") and req["description"].endswith("c")
