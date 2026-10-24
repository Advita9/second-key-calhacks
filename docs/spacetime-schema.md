# SpacetimeDB module (TypeScript) — room, turns, leaderboard

SpacetimeDB owns the multiplayer room. The kernel owns money. The bridge connects them.
Reducers cannot make network calls, so the bridge (a Node client with a registered identity) does the HTTP hop.

## Tables

| table | columns | notes |
|---|---|---|
| `room` | `id: string PK`, `code: string unique`, `status: lobby/live/debrief`, `policy_version`, `created_at` | one row per table demo |
| `player` | `identity: Identity PK`, `room_id`, `handle`, `role: attacker/observer/operator`, `joined_at` | handle filtered for PII/profanity |
| `turn` | `id: u64 autoinc PK`, `room_id`, `player: Identity`, `text`, `audio_url?`, `created_at`, `status: queued/processing/done` | attacker input; bridge claims `queued` rows |
| `margaret_reply` | `id autoinc PK`, `turn_id`, `text`, `audio_url`, `persuaded: bool`, `created_at` | what the board shows and plays |
| `outcome` | `id autoinc PK`, `turn_id`, `player`, `stage: u8`, `payment_id?`, `decision: ALLOW/HOLD/DENY/REFUSED`, `rule_ids: string[]`, `refusal?` | written only by bridge |
| `leaderboard` | `player: Identity PK`, `room_id`, `handle`, `best_stage: u8`, `attempts: u32`, `last_at` | maintained by `record_outcome` |
| `scoreboard` | `room_id PK`, `unauthorized_releases: u32`, `legit_completed: u32`, `attempts: u32` | the two headline numbers |
| `audit_mirror` | `seq PK`, `room_id`, `kind`, `hash`, `prev_hash`, `ts` | last 200 kernel audit events for the board; kernel SQLite is the source of truth |
| `config` | `id PK = 0`, `worker_identity: Identity` | set once at deploy |

## Reducers

- `create_room(code)` → inserts room, caller becomes operator.
- `join_room(code, handle)` → upserts player as attacker. Reject if room not lobby/live.
- `submit_turn(room_id, text)` → requires caller is attacker in that room; length ≤ 400; rate limit 1 turn / 3s per player (check `last_at`); inserts `turn(status=queued)`.
- `claim_turn(turn_id)` worker only → status=processing.
- `record_reply(turn_id, text, audio_url, persuaded)` worker only.
- `record_outcome(turn_id, stage, payment_id?, decision, rule_ids, refusal?)` worker only → inserts outcome, updates leaderboard (best_stage = max, attempts += 1), updates scoreboard (stage 100 → unauthorized_releases += 1).
- `record_legit_completed(room_id)` worker only → scoreboard.legit_completed += 1.
- `mirror_audit(room_id, seq, kind, hash, prev_hash, ts)` worker only.
- `set_room_status(room_id, status)` operator only.
- `reset_room(room_id)` operator only → clears turns/replies/outcomes/leaderboard/scoreboard for that room.

"worker only" = `ctx.sender === config.worker_identity`. "operator only" = player.role === operator.

## Subscriptions

- `/play`: `player`, `leaderboard` (room), own `outcome` rows (stage only, rule_ids hidden client-side AND not sent: use a view or strip in reducer).
- `/board`: everything for the room.
- `/ops`: everything plus `audit_mirror`.

## Bridge loop (`bridge/src/index.ts`)

1. Connect with saved identity token (`bridge/.identity`). On first run, print identity so it can be set in `config`.
2. Subscribe `SELECT * FROM turn WHERE status = 'queued'`.
3. For each row: `claim_turn`, POST kernel `/rooms/{room}/turns`, then `record_reply`, `record_outcome`, and `mirror_audit` for new audit events.
4. On kernel error: `record_outcome(stage=10, decision=HOLD, refusal="kernel unavailable, fail closed")`.
5. Idempotent: skip turn ids already in a local `done` set.

## Local dev

```
curl -sSf https://install.spacetimedb.com | sh
spacetime start                      # local server, port 3000
cd spacetime && spacetime publish --project-path . second-key
spacetime generate --lang typescript --out-dir ../frontend/src/module_bindings --project-path .
spacetime generate --lang typescript --out-dir ../bridge/src/module_bindings --project-path .
```
Maincloud later: `spacetime publish --server maincloud second-key` (needs login; Armaan in the morning).

## Fallback

If the CLI cannot be installed, implement `RoomStore` in `backend/kernel/room_memory.py` with the same tables, expose over the kernel WS, and keep the `spacetime/` module compiling (`npm run build` in `spacetime/`). Record in `docs/DECISIONS.md`.
