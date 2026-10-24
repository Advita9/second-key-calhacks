# Capital One Nessie research (researcher agent, 2026-10-23 22:30)

Primary source: official OpenAPI spec https://nessieisreal.com/nessie-openapi-spec.yaml (Nessie API 1.0.0). The documentation page at api.nessieisreal.com/documentation returns 403. Live behaviour below comes from third-party October 2026 reports and is marked as such.

## Corrections to our assumptions
1. Base URL must be `https://api.nessieisreal.com` (HTTPS). Plain http is refused (live reports). Spec also lists `https://prod-api.nessieisreal.com`. Make it an env var; our `.env` currently says `http://` and must be changed to `https://`.
2. `POST /accounts/{id}/transfers` is not in the official spec. Live reports: it accepts only `{transaction_date, status, amount, description}`, rejects `medium` and `payee_id`, and stays `pending`.
3. Balances never move in the sandbox. Every create returns 201; balance is fixed at creation.
4. Amounts are integer dollars. 12.34 is stored as 12.

## Endpoints (all take `?key=KEY`)
- `POST /customers` body `{first_name, last_name, address: {street_number, street_name, city, state, zip}}` (all strings, required). 201. SDK reads `body["objectCreated"]["_id"]`.
- `POST /customers/{customer_id}/accounts` body `{type: "Checking"|"Savings"|"Credit Card", nickname, rewards: int>=0, balance: int>=0}` all required. 201 with objectCreated wrapper.
- `GET /accounts/{id}` 200 Account `{_id, type, nickname, rewards, balance, account_number, customer_id}`; one live report saw it wrapped as `{"account": {...}}`. Unwrap if present. 404 if missing.
- `POST /accounts/{id}/withdrawals` body (field names not in spec; third parties use) `{medium: "balance", transaction_date: "YYYY-MM-DD", status: "completed", amount: int, description}`. 201.
- `POST /accounts/{id}/deposits` body `{medium, transaction_date, status, amount, description}` (spec: required). 201. One report says deposits also need `type`; send spec body first, add `type` only on 400.
- Best fit for "customer sends money to payee": withdrawal on payer account + deposit on payee account, both with our payment id in `description`. Store the withdrawal id as `nessie_transfer_id`.
- Error shape `{code, message, details}`; 401 body is bare `unauthorized`. Empty list GETs may return 404 (treat as empty).
- No rate limits documented.

## Client design
- `NessieClient(base_url=NESSIE_BASE_URL default https://api.nessieisreal.com, key=NESSIE_API_KEY)`, 15s timeout, `_created_id(body)` that accepts `objectCreated._id`, `_id`, `id`, else raises.
- Integer dollars at the boundary: `amount_cents // 100`, and put the exact cents in `description` so the ledger line is unambiguous.
- `MockNessie` mirrors the real shape: 201 `{"code":201,"message":...,"objectCreated":{...}}`, fixed balance, 404 on empty lists.
- Judge-facing copy: "payment recorded in the Nessie sandbox ledger", never "moved the money".

## Morning check
`curl -s "https://api.nessieisreal.com/customers?key=$NESSIE_API_KEY" | head -c 300` should be 200 with a JSON array.
