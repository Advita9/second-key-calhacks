---
name: spacetime-engineer
description: Builds the SpacetimeDB TypeScript module and the Node bridge per docs/spacetime-schema.md, or the in-memory RoomStore fallback if the CLI cannot be installed. Use for build-order task 9.
tools: Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch
model: inherit
effort: high
maxTurns: 80
---

You build `spacetime/` and `bridge/` for Second Key. Read docs/spacetime-schema.md first.

Facts from research (verify against https://spacetimedb.com/docs before relying on them; APIs changed in 2.0):
- Modules can be TypeScript. Reducers are transactional and cannot make network calls. Clients subscribe with SQL and get a local cache.
- Reducers do not return data; clients read via subscriptions. Auto-increment ids are not guaranteed sequential.
- Authorization inside reducers uses `ctx.sender`. Worker-only reducers compare against `config.worker_identity`.
- Local: `curl -sSf https://install.spacetimedb.com | sh`, `spacetime start`, `spacetime publish --project-path spacetime second-key`, `spacetime generate --lang typescript`.
- There is no official Python client SDK. The bridge is Node.

Steps:
1. Install CLI. If install fails twice, switch to the fallback (below) and record it in docs/DECISIONS.md.
2. Write the module: tables and reducers exactly as the schema doc lists. Rate limit and length checks in `submit_turn`. Strip `rule_ids` from anything attackers can subscribe to (separate `outcome_public` table with stage only, or a view if views are stable in this version).
3. `spacetime publish` locally, `spacetime generate` bindings into `frontend/src/module_bindings` and `bridge/src/module_bindings`.
4. Bridge: connect, persist identity token, subscribe to queued turns, call kernel `POST /rooms/{room}/turns`, write back. Retry with backoff. Idempotent on turn id. `npm run dev` starts it. Log every hop.
5. `tests/e2e/test_room.sh`: start kernel (mock mode), start bridge, insert a turn with the CLI or a tiny TS client, assert an `outcome` row appears within 10s.
6. Write `docs/SPACETIME_NOTES.md`: identity setup command for Armaan, how to publish to maincloud in the morning, what to say to the SpacetimeDB judge (what was hard without Spacetime: fan-out to 30 phones, shared leaderboard, ordered turn queue with claims).

Fallback RoomStore: `backend/kernel/room_memory.py` with the same tables as dicts, exposed over the kernel WS; frontend uses a `RoomClient` interface with two implementations (spacetime, ws). Keep `spacetime/` compiling so the module still ships.
