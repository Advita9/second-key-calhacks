# SpacetimeDB notes (room backend)

Written overnight by the spacetime lane. Verified live against the repo-local CLI
and server, SpacetimeDB 2.13.0, no spacetimedb.com login.

## What runs where

- `spacetime/src/index.ts` is the module: 9 tables, 11 reducers, 1 view, `init`.
- `bridge/` is the worker: the only identity allowed to write outcomes.
- `backend/kernel/room_memory.py` + `backend/api/room_ws.py` are the fallback (`ROOM_BACKEND=memory`), same tables, same limits, same stripping.
- Bindings are generated into `bridge/src/module_bindings/` and `frontend/src/module_bindings/` and committed. Regenerate with `scripts/gen-bindings.sh` after editing the module. Both consumers need the npm package `spacetimedb@2.13.0` (same version as the CLI or the bindings do not compile).

## CLI (repo-local, every command)

```
st() { .tools/spacetime/spacetime --root-dir="$PWD/.tools/spacetime" "$@"; }
curl -s localhost:3000/v1/ping || (nohup .tools/spacetime/spacetime --root-dir="$PWD/.tools/spacetime" start > .claude/spacetime.log 2>&1 &)
st publish --module-path spacetime --server local --yes second-key
st sql --server local --yes second-key 'SELECT * FROM outcome'
st call --server local --yes second-key create_room '"DEMO"'
```
`--server local` on every call (config default is maincloud). `--yes` skips the login prompt. Flag is `--module-path`, not `--project-path`.

## Identity setup (the owner gate)

Verified tonight: `init` runs with `ctx.sender` = the publishing identity, so `config.owner_identity` is the CLI identity that ran `publish`. Only that identity can call `set_worker_identity`. Non-owner callers get `SenderError('owner only')`. No first-come fallback was needed.

Steps, in order, after the server is up and the module is published:

```
(cd bridge && npm run dev)                      # prints: connected identity=<hex>, writes bridge/.identity.hex
st call --server local --yes second-key set_worker_identity "\"$(cat bridge/.identity.hex)\""
st sql --server local --yes second-key 'SELECT * FROM config'   # worker_identity_hex now set
```
The bridge keeps its token in `bridge/.spacetimedb-token` (gitignored) so the identity survives restarts. Delete that file and you must authorize the new identity again. Until it is authorized, the bridge logs `claim.retry ... no worker identity configured` and picks up queued turns the moment it is.

Exact lines for `scripts/dev.sh` (lead wires them):
```
spacetime_cli start                                   # background, port 3000, if /v1/ping fails
spacetime_cli publish --module-path spacetime --server local --yes second-key
(cd bridge && KERNEL_URL=http://127.0.0.1:8000 nohup npm run dev > .claude/bridge.log 2>&1 & echo $! > .claude/bridge.pid)
until [ -s bridge/.identity.hex ]; do sleep 0.5; done
spacetime_cli call --server local --yes second-key set_worker_identity "\"$(cat bridge/.identity.hex)\""
```

## Roles

- `create_room(code)`: caller becomes the room operator. Call it from the ops laptop.
- `join_room(code, handle)`: upserts the caller as an attacker. If the ops laptop joins from `/play` it loses operator (same browser identity). Use a phone or a private window for `/play`.
- `submit_turn(roomId, text)`: attackers only; 1 to 400 chars; one per 3 s per player (`ctx.timestamp` vs `player.lastTurnAt`).
- Worker-only reducers (`claim_turn`, `record_reply`, `record_outcome`, `record_legit_completed`, `mirror_audit`) compare `ctx.sender.toHexString()` to `config.workerIdentityHex` and throw `SenderError('worker only')`.
- Operator-only: `set_room_status`, `reset_room`.
- `decision` values: `ALLOW | HOLD | DENY | REFUSED | NONE`. `NONE` means no payment was attempted on that turn (Margaret was not persuaded); `stage` still records how far the attacker got.

## What attackers can see

`my_outcomes` is a public view filtered to `ctx.sender`. Its row type is `{turnId, stage, decision}`. Rule ids and refusal text are not in the row type, so they never leave the server for a phone. Verified with the scripted attacker: `keys: ["turnId","stage","decision"]`. The board subscribes to `outcome` directly (it is public and holds rule ids; the projector is the bank's view).

Memory mode mirrors this: `RoomStore.snapshot(room, "attacker", player_id)` returns `myOutcomes` with those three keys, `outcomes: []`, only the player's own turns and replies, and no audit.

## Bridge

```
cd bridge && npm install && npm run dev          # env below
npm test                                         # guard (never mutates payments, never says release), tsc, node tests
npm run submit-turn -- --room DEMO --handle probe --text "..."   # scripted attacker, prints the my_outcomes row
```
Env: `KERNEL_URL` (default `http://127.0.0.1:8000`), `SPACETIME_URI`, `SPACETIME_DB`, `ROOM_CODE` (default `DEMO`, the room whose scoreboard gets legit completions), `BRIDGE_TOKEN` or `OPS_TOKEN` (sent as `X-Ops-Token` on every kernel request; `BRIDGE_TOKEN` wins, falls back to `OPS_TOKEN`; the kernel requires it on `/rooms/{room}/turns` when either is set), `KERNEL_TIMEOUT_MS` (default 25000, matches the real-mode turn budget), `LEGIT_POLL_MS` (default 3000).

Turn loop: subscribe `SELECT * FROM turn WHERE status = 'queued'` -> `claim_turn` -> `POST ${KERNEL_URL}/rooms/{room}/turns {turn_id, player_id, text}` (25 s timeout, 2 retries with backoff on transport errors and 5xx) -> `record_reply` -> `record_outcome` (`outcome: null` -> decision `NONE`) -> `mirror_audit` for seqs above the last seen from `GET /audit?limit=50`. Kernel error, timeout or malformed body -> `record_outcome(stage 10, HOLD, [], "kernel unavailable, fail closed")`. Idempotent per turn id in-process, and `record_outcome` in the module ignores a second outcome for the same turn. Every hop is one log line.

Legit completions (the second headline number): every 3 s the bridge does a read-only `GET /payments?limit=200`. A payment that is `SUBMITTED`, not seen before, and whose `conversation_id` is not a room conversation (`room_<CODE>` from `kernel/rooms.py`, or a bare room code, or any `room_` prefix) triggers `record_legit_completed(ROOM_CODE)` and one log line `legit.completed payment=... room=...`. A `SUBMITTED` payment that came from a room turn is a breach, already counted by `record_outcome(stage 100)`, and is never counted as legit. The first poll only primes the seen set, so payments submitted before the bridge started are not counted. The seen set lives in memory. Logic is pure in `bridge/src/legit.ts` with node tests in `legit.test.ts`.

Verified live 2026-10-24 06:26 against the real kernel in mock mode: a room turn produced a Margaret reply row and an outcome `stage 10, NONE`; scenario B (L-01 known biller, create -> BANK_REVIEW certificate -> release -> SUBMITTED) moved `scoreboard.legit_completed` for DEMO from 0 to 1 within one poll.

## Memory mode (fallback)

```
cd backend && uv run uvicorn api.room_memory_app:app --port 8011
POST /rooms/{room}/join {handle} -> {player_id, player_token, room_id}
POST /rooms/{room}/submit {text} + X-Player-Token -> {turn_id}
GET  /rooms/{room}/snapshot?role=attacker|board|ops&player_id=
WS   /ws?room=&role=&player_id=   -> {type:"room", snapshot} on every change; accepts {type:"submit_turn", text, player_token}
```
Rooms are auto-created on first join in memory mode. `RoomHub(taker=..., audit=...)` takes a `TurnTaker` (`take_turn(room_id, turn_id, player_id, text) -> api.md turn dict`) and an optional `AuditSource` (`recent(limit)`); `StubTurnTaker` answers with a fixed line and stage 10. `hub.broadcast_event({...})` relays kernel `payment` / `margaret` / `attack` messages to every socket.

## Tests

```
cd spacetime && npm run build                  # tsc --noEmit, no CLI needed
cd bridge && npm test
cd backend && uv run pytest -q tests/unit/test_room_memory.py tests/api/test_room_ws.py
tests/e2e/test_room.sh                         # spacetime branch if :3000 answers, else memory
ROOM_BACKEND=memory tests/e2e/test_room.sh     # force the memory branch
```
The spacetime branch checks whether `${KERNEL_URL:-http://127.0.0.1:8000}/health` answers. If it does, it requires a real decision (`NONE|HOLD|DENY`, never the fail-closed refusal) and a `margaret_reply` row for the same turn. If the kernel is down it accepts the fail-closed stage-10 HOLD outcome. Start the kernel for the full check:
```
cd backend && KERNEL_DB=:memory: MOCK_EXTRACTOR=1 MOCK_MARGARET=1 ROOM_BACKEND=memory DEMO_MODE=1 TTS_PROVIDER=mock STT_PROVIDER=mock KERNEL_LOAD_DOTENV=0 uv run uvicorn api.main:app --port 8000
```

## Maincloud in the morning (Armaan)

1. `st login` (browser). This creates a new identity in the CLI config; the local-only identity will not carry over. Expected.
2. `st publish --module-path spacetime --server maincloud --yes second-key` (pick another name if taken).
3. Start the bridge with `SPACETIME_URI=wss://maincloud.spacetimedb.com SPACETIME_DB=second-key`, delete `bridge/.spacetimedb-token` first so it gets a maincloud identity, then `st call --server maincloud --yes second-key set_worker_identity "\"$(cat bridge/.identity.hex)\""`.
4. Frontend: `NEXT_PUBLIC_SPACETIME_URI=wss://maincloud.spacetimedb.com`, `NEXT_PUBLIC_ROOM_BACKEND=spacetime`.
5. Bindings do not change between local and maincloud.
If maincloud is slow or down, stay local: phones on the same Wi-Fi reach `ws://<laptop-ip>:3000` (the server binds 0.0.0.0).

## What to tell the SpacetimeDB judge

- The room is a SpacetimeDB database. Thirty phones subscribe to the same tables and get every leaderboard and scoreboard change pushed, no polling, no fan-out code on our side.
- The turn queue is a table. `submit_turn` is a transactional reducer that enforces length and a per-player rate limit using the server clock; the bridge claims rows with `claim_turn` so two workers can never process the same turn.
- Authorization lives in reducers. Only the database owner can authorize the worker identity, and only that identity can write an outcome. The model and the players have no path to those rows.
- Secrecy by view: attackers subscribe to `my_outcomes`, a view whose row type has no rule ids. What they cannot see cannot be optimized against.
- Both headline numbers live in one row: `scoreboard.unauthorized_releases` (written by `record_outcome` when a room turn reaches stage 100) and `scoreboard.legit_completed` (written by `record_legit_completed` when a non-room payment settles). Every phone and the projector see the same row change at the same time.
- The kernel's hash chain is mirrored into `audit_mirror` so the projector shows the chain live, while SQLite in the kernel stays the source of truth.
- Hard without it: fan-out to 30 phones, a shared leaderboard that stays consistent under concurrent writes, and an ordered turn queue with claims would each be a service of their own.

## UNVERIFIED / known gaps

- The bridge with `OPS_TOKEN` set on the kernel side (verified only with the token unset; the header is sent whenever `BRIDGE_TOKEN` or `OPS_TOKEN` is in the bridge env).
- Legit completion with the real extractor (verified with mocks only; the logic does not depend on the extractor).
- Maincloud publish (needs login).
- Behaviour when two bridges run with different identities: the second one keeps retrying `claim` until it is authorized. Run one bridge.
- `reset_room` iterates `turn` and `audit_mirror`; fine for a demo-sized room.
