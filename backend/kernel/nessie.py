"""Capital One Nessie sandbox client and the `TransferRail` built on it.

Facts (docs/research/nessie.md): HTTPS base `https://api.nessieisreal.com`, every call takes
`?key=`, creates return 201 `{"code": 201, "message": ..., "objectCreated": {"_id": ...}}`,
amounts are integer dollars, balances never move. A "transfer" is a withdrawal on Margaret's
account plus a deposit on the payee account, both carrying `second-key <payment.id> <cents>c`
in the description so the ledger line is unambiguous. The withdrawal id is the transfer id.

`MockNessieTransport` is an httpx transport that mirrors those shapes, so the same client
code runs against the sandbox and in tests. Labelled MOCK in `/health`.

The kernel calls `NessieRail.submit` only inside a verified release; any failure raises
`RailError` and the kernel rolls the release back (I1). No secret is ever logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx

from kernel.models import Certificate, Payment
from kernel.rail import RailError, RailUnknownOutcome

log = logging.getLogger("second_key.nessie")

DEFAULT_BASE_URL = "https://api.nessieisreal.com"
MOCK_KEY = "mock-nessie-key"
MARGARET_ACCOUNT_REF = "acc_margaret"
MARGARET_BALANCE_DOLLARS = 24_000
PAYEE_BALANCE_DOLLARS = 0
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def default_cache_path() -> Path:
    # backend/kernel/nessie.py -> backend/cache/nessie_payees.json
    return Path(__file__).resolve().parents[1] / "cache" / "nessie_payees.json"


def created_id(body: object) -> str:
    """Id of a created object: `objectCreated._id`, else `_id`, else `id`. Raises RailError."""
    if isinstance(body, Mapping):
        created = body.get("objectCreated")
        if isinstance(created, Mapping):
            for k in ("_id", "id"):
                v = created.get(k)
                if isinstance(v, str) and v:
                    return v
        for k in ("_id", "id"):
            v = body.get(k)
            if isinstance(v, str) and v:
                return v
    raise RailError("nessie: response carries no created id")


def dollars(amount_cents: int) -> int:
    """Integer dollars at the Nessie boundary. Never below 1 so a sub-dollar ledger line still
    exists; the exact cents travel in the description."""
    return max(1, amount_cents // 100)


class NessieClient:
    """Thin JSON client. `transport` is injectable so tests and mock mode use no network."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        key: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not key:
            raise ValueError("NessieClient needs a key")
        self._key = key
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    def close(self) -> None:
        self._http.close()

    # ---------------------------------------------------------------- raw calls

    def request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        try:
            r = self._http.request(method, path, params={"key": self._key}, json=body)
        except httpx.HTTPError as e:
            raise RailError(f"nessie: {type(e).__name__}") from e
        if r.status_code == 401:
            raise RailError("nessie: unauthorized (401)")
        if r.status_code == 404:
            raise RailError(f"nessie: not found (404) {method} {path}")
        if r.status_code >= 400:
            raise RailError(f"nessie: {method} {path} -> {r.status_code} {_short(r.text)}")
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError as e:
            raise RailError("nessie: non-JSON body") from e

    def get_account(self, account_id: str) -> dict[str, Any]:
        body = self.request("GET", f"/accounts/{account_id}")
        if isinstance(body, Mapping) and isinstance(body.get("account"), Mapping):
            body = body["account"]
        if not isinstance(body, Mapping):
            raise RailError("nessie: account body is not an object")
        return dict(body)

    def create_customer(self, first_name: str, last_name: str) -> str:
        body = self.request(
            "POST",
            "/customers",
            {
                "first_name": first_name,
                "last_name": last_name,
                "address": {
                    "street_number": "1",
                    "street_name": "Demo Street",
                    "city": "Oakland",
                    "state": "CA",
                    "zip": "94612",
                },
            },
        )
        return created_id(body)

    def create_account(
        self, customer_id: str, nickname: str, balance_dollars: int, kind: str = "Checking"
    ) -> str:
        body = self.request(
            "POST",
            f"/customers/{customer_id}/accounts",
            {"type": kind, "nickname": nickname, "rewards": 0, "balance": balance_dollars},
        )
        return created_id(body)

    def withdraw(self, account_id: str, amount_dollars: int, description: str) -> str:
        body = self.request(
            "POST", f"/accounts/{account_id}/withdrawals", _tx(amount_dollars, description)
        )
        try:
            return created_id(body)
        except RailError as e:
            # The sandbox accepted the withdrawal but we cannot name it: money may have moved.
            raise RailUnknownOutcome(f"nessie: withdrawal accepted but {e}") from e

    def deposit(self, account_id: str, amount_dollars: int, description: str) -> str:
        """Spec body first; one live report says deposits need `type`, so retry with it on 400."""
        try:
            body = self.request(
                "POST", f"/accounts/{account_id}/deposits", _tx(amount_dollars, description)
            )
        except RailError as e:
            if "400" not in str(e):
                raise
            log.info("nessie.deposit.retry_with_type")
            body = self.request(
                "POST",
                f"/accounts/{account_id}/deposits",
                {**_tx(amount_dollars, description), "type": "deposit"},
            )
        return created_id(body)


def _tx(amount_dollars: int, description: str) -> dict[str, Any]:
    return {
        "medium": "balance",
        "transaction_date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "status": "completed",
        "amount": amount_dollars,
        "description": description,
    }


def _short(text: str, n: int = 160) -> str:
    return text[:n].replace("\n", " ")


# ---------------------------------------------------------------- mock transport


class MockNessieTransport(httpx.BaseTransport):
    """In-process Nessie. Same URL shapes, same 201 wrapper, 404 unknown ids, 401 bad key.

    Seeded with `acc_margaret` so Margaret's account exists without a create call. Every
    withdrawal and deposit is kept in `ledger` for tests. Balances never move, as in the
    sandbox. `fail_with` makes the next write fail (rail failure tests).
    """

    def __init__(self, key: str = MOCK_KEY) -> None:
        self.key = key
        self.customers: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, Any]] = {
            MARGARET_ACCOUNT_REF: {
                "_id": MARGARET_ACCOUNT_REF,
                "type": "Checking",
                "nickname": "Margaret checking",
                "rewards": 0,
                "balance": MARGARET_BALANCE_DOLLARS,
                "account_number": "0000000000000001",
                "customer_id": "cust_margaret",
            }
        }
        self.ledger: list[dict[str, Any]] = []
        self.fail_with: int | None = None
        self.fail_after_writes: int = 0  # let this many writes through before `fail_with` fires
        self._n = 0
        self._lock = threading.Lock()

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n:06d}"

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            return self._handle(request)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        qs = parse_qs(request.url.query.decode())
        if qs.get("key", [""])[0] != self.key:
            return httpx.Response(401, text="unauthorized")
        path = request.url.path.rstrip("/")
        method = request.method
        body: dict[str, Any] = {}
        if request.content:
            try:
                loaded = json.loads(request.content)
            except ValueError:
                return _err(400, "malformed JSON")
            if isinstance(loaded, dict):
                body = loaded
        parts = path.strip("/").split("/")

        if method == "POST" and parts == ["customers"]:
            for k in ("first_name", "last_name", "address"):
                if k not in body:
                    return _err(400, f"missing {k}")
            cid = self._next("cust")
            self.customers[cid] = {"_id": cid, **body}
            return _created("Customer created", cid)

        if (
            method == "POST"
            and len(parts) == 3
            and parts[0] == "customers"
            and parts[2] == "accounts"
        ):
            if parts[1] not in self.customers:
                return _err(404, "customer not found")
            for k in ("type", "nickname", "rewards", "balance"):
                if k not in body:
                    return _err(400, f"missing {k}")
            aid = self._next("acc")
            self.accounts[aid] = {
                "_id": aid,
                **body,
                "account_number": f"{self._n:016d}",
                "customer_id": parts[1],
            }
            return _created("Account created", aid)

        if method == "GET" and len(parts) == 2 and parts[0] == "accounts":
            acc = self.accounts.get(parts[1])
            if acc is None:
                return _err(404, "account not found")
            return httpx.Response(200, json=acc)

        if method == "POST" and len(parts) == 3 and parts[0] == "accounts":
            kind = parts[2]
            if kind not in {"withdrawals", "deposits"}:
                return _err(404, "no such route")
            if parts[1] not in self.accounts:
                return _err(404, "account not found")
            if self.fail_with is not None:
                if self.fail_after_writes > 0:
                    self.fail_after_writes -= 1
                else:
                    code, self.fail_with = self.fail_with, None
                    return _err(code, "simulated failure")
            for k in ("medium", "transaction_date", "status", "amount", "description"):
                if k not in body:
                    return _err(400, f"missing {k}")
            if not isinstance(body["amount"], int) or body["amount"] < 0:
                return _err(400, "amount must be a non-negative integer")
            tid = self._next("wd" if kind == "withdrawals" else "dp")
            self.ledger.append({"_id": tid, "kind": kind[:-1], "account": parts[1], **body})
            return _created(f"{kind[:-1].capitalize()} created", tid)

        return _err(404, "no such route")


def _created(message: str, oid: str) -> httpx.Response:
    return httpx.Response(
        201, json={"code": 201, "message": message, "objectCreated": {"_id": oid}}
    )


def _err(code: int, message: str) -> httpx.Response:
    return httpx.Response(code, json={"code": code, "message": message})


# ---------------------------------------------------------------- the rail


class _IdCache:
    """`{"accounts": {account_ref: nessie_account_id}, "customers": {...}}` on disk, or in
    memory when `path` is None (mock mode, tests). Writes are atomic."""

    def __init__(self, path: Path | None, seed: Mapping[str, str] | None = None) -> None:
        self.path = path
        self.accounts: dict[str, str] = dict(seed or {})
        self.customers: dict[str, str] = {}
        self._lock = threading.Lock()
        if path is not None and path.is_file():
            try:
                loaded = json.loads(path.read_text("utf-8"))
                self.accounts.update(_str_map(loaded.get("accounts")))
                self.customers.update(_str_map(loaded.get("customers")))
            except (OSError, ValueError, AttributeError):
                log.warning("nessie.cache.unreadable", extra={"path": str(path)})

    def get(self, ref: str) -> str | None:
        return self.accounts.get(ref)

    def put(self, ref: str, account_id: str, customer_id: str) -> None:
        with self._lock:
            self.accounts[ref] = account_id
            self.customers[ref] = customer_id
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(
                json.dumps(
                    {"accounts": self.accounts, "customers": self.customers},
                    indent=1,
                    sort_keys=True,
                ),
                "utf-8",
            )
            os.replace(tmp, self.path)


def _str_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}


class NessieRail:
    """`TransferRail` over Nessie: withdrawal on the payer account, deposit on the payee.

    Payee and payer accounts are created lazily (one customer + one checking account per
    `account_ref`) and remembered in the id cache. `payee_accounts` pre-seeds that map.
    """

    def __init__(
        self,
        client: NessieClient,
        *,
        payee_accounts: Mapping[str, str] | None = None,
        cache_path: Path | None = None,
    ) -> None:
        self.client = client
        self._ids = _IdCache(cache_path, payee_accounts)
        self._lock = threading.RLock()

    def account_for(self, ref: str) -> str:
        """Nessie account id for an account_ref, creating customer + account on first use."""
        if not _ID_RE.match(ref):
            raise RailError("nessie: account_ref has characters outside [A-Za-z0-9_-]")
        with self._lock:
            hit = self._ids.get(ref)
            if hit is not None:
                return hit
            first, last = _names_for(ref)
            customer_id = self.client.create_customer(first, last)
            balance = (
                MARGARET_BALANCE_DOLLARS if ref == MARGARET_ACCOUNT_REF else PAYEE_BALANCE_DOLLARS
            )
            account_id = self.client.create_account(customer_id, ref, balance)
            self._ids.put(ref, account_id, customer_id)
            log.info("nessie.account.created", extra={"ref": ref, "account_id": account_id})
            return account_id

    def submit(self, payment: Payment, certificate: Certificate) -> str:
        description = f"second-key {payment.id} {payment.amount_cents}c"
        amount = dollars(payment.amount_cents)
        try:
            payer = self.account_for(payment.account_id)
            payee = self.account_for(payment.beneficiary.account_ref)
            withdrawal_id = self.client.withdraw(payer, amount, description)
        except RailError:
            raise  # includes RailUnknownOutcome from an unparseable withdrawal response
        except Exception as e:  # noqa: BLE001  anything else before money moved is a plain failure
            raise RailError(f"nessie: {type(e).__name__}") from e
        try:
            deposit_id = self.client.deposit(payee, amount, description)
        except Exception as e:  # noqa: BLE001  withdrawal happened; the outcome is now unknown
            raise RailUnknownOutcome(
                f"nessie: deposit failed after withdrawal {withdrawal_id}: {type(e).__name__}",
                partial_ref=withdrawal_id,
            ) from e
        log.info(
            "nessie.transfer",
            extra={
                "payment_id": payment.id,
                "certificate_id": certificate.id,
                "withdrawal_id": withdrawal_id,
                "deposit_id": deposit_id,
                "amount_dollars": amount,
            },
        )
        return withdrawal_id


def _names_for(ref: str) -> tuple[str, str]:
    if ref == MARGARET_ACCOUNT_REF:
        return "Margaret", "Demo"
    tail = ref.removeprefix("ext_").removeprefix("acc_") or ref
    words = [w for w in re.split(r"[_-]+", tail) if w]
    first = (words[0] if words else tail).capitalize()
    last = " ".join(w.capitalize() for w in words[1:]) or "Payee"
    return first[:40], last[:40]


def build_rail(env: Mapping[str, str]) -> tuple[NessieRail, str]:
    """`NESSIE_API_KEY` set -> sandbox over HTTPS with the on-disk id cache; else MOCK transport
    with an in-memory cache (mock ids must never mix with sandbox ids)."""
    key = env.get("NESSIE_API_KEY", "").strip()
    if not key:
        log.info("nessie.mode", extra={"mode": "mock"})
        client = NessieClient(key=MOCK_KEY, transport=MockNessieTransport())
        return NessieRail(
            client, payee_accounts={MARGARET_ACCOUNT_REF: MARGARET_ACCOUNT_REF}
        ), "mock"
    base_url = env.get("NESSIE_BASE_URL", "").strip() or DEFAULT_BASE_URL
    if base_url.startswith("http://"):
        base_url = "https://" + base_url[len("http://") :]
    cache_override = env.get("NESSIE_CACHE_PATH", "").strip()
    cache_path = Path(cache_override) if cache_override else default_cache_path()
    log.info("nessie.mode", extra={"mode": "real", "base_url": base_url})
    return NessieRail(NessieClient(base_url=base_url, key=key), cache_path=cache_path), "real"
