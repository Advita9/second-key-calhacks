# QA report: judge rehearsal

Run 2026-10-23 23:30 to 00:00 PDT against the live stack (`.env` as is: real extractor, real Margaret, Cartesia, Nessie sandbox, SpacetimeDB). Only `docs/MORNING.md` and `README.md` were used as instructions, plus the lead's note that `scripts/dev.sh start` prints the ops token and that the room is DEMO. Nothing was fixed. Screenshots are in `frontend/e2e/screenshots/qa-*.png` (list at the end).

```
BLOCKERS (demo breaks):
  1. Kernel crash mid-turn hangs the phone. Killed the :8000 listener 0.6 s after Send. /play showed "Margaret is thinking", stage 0, status chip RECONNECTING, and a footer chip "KERNEL: KERNEL RETURNED 500" for the full 60 s observation. No stage 10, no "kernel unavailable, fail closed", nothing on /board (board showed "Kernel WS: reconnecting (attempt 9)"). The turn never reached SpacetimeDB (bridge log has no claim), because /play submits through the kernel WS (ws://localhost:8000/ws?room=DEMO&role=attacker), so the fail-closed path in the bridge never runs. MORNING section 2 item 5 describes a stage 10 fail-closed outcome that does not happen. Shots: qa-play-killed.png, qa-board-killed.png.
  2. First restart of the night bricked payments. After the first kernel process died (it had written 45 audit rows, no backend/second_key.db.head.json sidecar existed on disk), both `scripts/dev.sh start` and a clean `dev.sh stop; dev.sh start` came up with /health audit {"ok":false,"anchor":"mismatch","first_bad_seq":1}, /audit/verify red, and every POST /payments (with the token) returned 503 "SETTLEMENT REFUSED · AUDIT_ANCHOR_MISMATCH". /ops would show "Broken at seq 1" with no tamper. Only `scripts/dev.sh start --fresh` recovers, and --fresh is not in MORNING.md or README.md. Reproduced once out of two hard kills (second hard kill restarted with anchor ok, length 10). The untracked file backend/tests/redteam/test_found_audit_verifier_lies_after_restart.py suggests someone already saw this; it is not committed.
  3. "Change payee after approval" does nothing useful on the live stack. With .env DEMO_MODE=0 the kernel returns 404 for POST /attack/mutate even with the token, and the board prints "ATTACK ROUTE NOT LIVE YET" in red (qa-board-attack-mutate.png). TABLE_SCRIPT 1:10 beat ("Press Change payee after approval, I2_FINGERPRINT") fails as documented. Same root cause: /ops has no tamper button in live mode, so the "verify, tamper, verify again" beat cannot be shown either. MORNING only says DEMO_MODE=1 is for "the offline demo script and the tamper button".
  4. `cd backend && DEMO_MODE=1 uv run python ../scripts/demo.py --real` prints result : FAIL. Every step gets 401 {"refused":true,"reason":"ops token required"} because .env sets OPS_TOKEN and demo.py --real does not send it; llm cache line reads hits=0 misses=0. MORNING gap 2 says to expect misses=0 and PASS. (Plain demo.py without --real passes in 0.64 s.)
  5. `scripts/acceptance.sh` ends ACCEPTANCE: RED. Only failing gate is "G8 docs/STATUS.md still has unchecked gates" (G1, G7, G8 and item 14 unchecked). MORNING section 2 item 1 says expect GREEN. 235.6 s wall.

ROUGH (judge would notice):
  1. Join wipe. Type a handle within about 0.5 s of /play loading (status chip still IDLE) and the handle input is cleared when the room connection opens; Join stays disabled until you retype. On localhost the window is small; on venue Wi-Fi it is the whole connect time. Reproduced 3 of 3 with delay 0, never with delay 500 ms+. This cost the first full rehearsal run (no turns went through).
  2. MORNING section 2 item 3 as written fails: `curl -s -X POST localhost:8000/attack/mutate` and `/attack/replay` return 401 {"refused":true,"reason":"ops token required"} under dev.sh (no X-Ops-Token in the doc). With the header, replay gives I3_REPLAY and mutate gives 404 (blocker 3).
  3. `.claude/kernel.pid` is the `uv run` wrapper, not uvicorn. `kill $(cat .claude/kernel.pid)` (MORNING gap 1 stopgap, and the kill test instruction) leaves the kernel listening on :8000 as an orphan; the turn completed normally. `dev.sh stop` is fine (pkill -P then kill). To actually stop it: `lsof -ti :8000 | xargs kill`.
  4. Real Margaret does not agree. Three scripted attacks (IRS arrest, secrecy, bank fraud department $5,000 wire) and the MORNING IRS line all stayed at stage 10 "Engaged"; no payment card ever appeared from a phone turn. Board LIVE PAYMENT only ever showed attack-panel payments or the curl-seeded one. The table script's 0:45 beat ("first payment appears HELD") needs a scripted persuasion path in real mode; demo.py's three-line warmth script is only proven in mock.
  5. One Margaret per room, shared across players. A fresh player (killtest50) got "First you were the IRS, then my bank, and now the IRS again" in reply to their first message, because judge7's turns were in the same conversation. /play copy says "Your messages go to Margaret and the bank, not to other players", which a judge will read as a private conversation.
  6. "Replay old approval" creates a real $8,000 Bay Roofing payment, SUBMITTED, with a real Nessie sandbox withdrawal, on every click, and the board's LEGITIMATE COMPLETED counter goes up by one each time (saw 1, 2, 3 after three clicks; bridge log "legit.completed"). Pressing the attack buttons five times shows 5 legitimate completions. Also the Margaret card balance changed from $24,000 to $8,000 after the attack panel ran, and back to $24,000 after a restart.
  7. Smoke command from README fails with the stack up. `cd frontend && npx playwright test e2e/smoke.spec.ts` with dev.sh running: 2 failed, 6 passed, 32 s (attack panel without token shows "OPERATOR TOKEN REQUIRED"; ops test's POST /payments gets 401). reuseExistingServer:true means it runs against whatever is on :8000. With the stack stopped it passes 8 of 8 in 12 s.
  8. Holds queue loses rule ids across a restart: the hold created before `dev.sh stop; start` shows an empty RULES column; the one created after shows H-01..H-07 (qa-ops.png). The board also shows "No payment yet" on a fresh load even when a HELD payment exists; it only shows pushed events.
  9. /ops "RULE HITS (EVAL / LIVE)" live column stayed 0 for every rule after attack-panel decisions (A-01, H-01, H-03) in the same kernel session.
  10. Next.js dev badge ("N" circle, bottom left) is on every page because dev.sh runs `npm run dev`; on /play at 390x844 it covers the left of the ALL PROVIDERS REAL badge (qa-play.png, qa-play-turn3.png).
  11. Board at 1920x1080: with a long LAST REPLY the PERSUADED label and bar are clipped at the bottom of the Margaret card (qa-board-attack-mutate.png).
  12. MORNING line 14 create_room prints a red "Error: Response text: room exists ... HTTP status server error (530)" block. The doc says "if it says room exists, fine" but a judge-side reader sees Error. dev.sh start already creates the room ("room DEMO already exists"), so MORNING's "Nothing else creates it" is stale.
  13. Docs stale versus the build: MORNING says OPS_TOKEN and MOCK_MARGARET are "not in .env" (both are); gap 1 (no token field on /ops) is fixed (field exists, ?token= works, approve as BANK_REVIEW worked and the board flipped to ELIGIBLE TO SUBMIT); gap 3 and README "Honest limits" say nothing calls record_legit_completed (the bridge does); README says eight rules, backend/kernel/policy/v1.yaml has nine (H-07 shows on /ops and in live decisions).
  14. Self-approve refusal text differs by surface: board shows "ATTESTATION REFUSED · I5_CONFLICT", README table says "409 I5_CONFLICT", demo.py prints "SETTLEMENT REFUSED · I5_CONFLICT" on one line and "ATTESTATION REFUSED · I5_CONFLICT" on the next.
  15. Eight untracked backend/tests/redteam/test_*.py files in the working tree, three named test_found_* (audit verifier after restart, compromised extractor allows S-05, I5 conflict normalization). Not run by acceptance; lead should read them before judging.
  16. dev.sh start restarts the frontend every time ("stopped frontend"), so open board and phone pages drop and reconnect.

COPY (writing rule violations):
  1. docs/spacetime-schema.md line 1 has an em dash in the title (between "(TypeScript)" and "room, turns, leaderboard"). Everything else scanned clean: grep for tamper-proof, physically cannot, em dash, speaker id, employer names over frontend/src, README.md, docs/MORNING.md, docs/DEVPOST_DRAFT.md, docs/TABLE_SCRIPT.md, fixtures/margaret.md found nothing.
  2. /play footer chip during a kernel outage reads "KERNEL: KERNEL RETURNED 500" (doubled word). Judge-visible in blocker 1.
  3. Board refusal text "ATTACK ROUTE NOT LIVE YET" is a developer message on the projector (blocker 3).
  4. MOCK badge: all providers were real, the UI showed "ALL PROVIDERS REAL" on board, play and ops. No MOCK badge needed and none shown. /ops policy panel shows "Extractor mock" (from eval/latest.json) next to the ALL PROVIDERS REAL chip; a judge may read that as a contradiction.
  5. Attack refusal strings, exactly as rendered on /board with the token:
       inject:       "HELD · H-01 H-03 (model said no concerns)"   rules: "POLICY_HOLD H-01 H-03"
       mutate:       "ATTACK ROUTE NOT LIVE YET"                   (DEMO_MODE=0; mock run gives "SETTLEMENT REFUSED · I2_FINGERPRINT")
       replay:       "SETTLEMENT REFUSED · I3_REPLAY"
       self-approve: "ATTESTATION REFUSED · I5_CONFLICT"

TIMING: demo.py 0.64s (demo mode, PASS; --real 0.65s, FAIL), first board render 62 to 82ms from domcontentloaded to Margaret card (HTTP 200 in 26ms; WS and room state settled within 1.5s), turn round trip 5.2s / 12.5s / 12.0s for the three attacks and 6.8s for the MORNING IRS line (send click to Margaret text visible on the phone; audio element started playing within the same window, 13 to 14 s WAV from the kernel /audio cache, /health tts "real"), scripts/dev.sh start 4.9s first run, 3.7 to 4.2s after, dev.sh stop 0.08s, scripts/acceptance.sh 235.6s (RED, G8 STATUS.md), smoke 32s live (2 failed) and 12s isolated (8 passed).
```

## What worked

- Health: ok, policy v1, every provider real, room spacetime. Eval line prints `0 40 40 0.8 mock`.
- Three phone turns got real Margaret replies, out loud on the phone, leaderboard moved (judge7, best 10, tries 3), stage bar at 10.
- With the token: inject, replay and self-approve refuse with the invariant named; the board and /ops render the steps.
- Approve as BANK_REVIEW on /ops (token via `?token=`) lifted a seeded HELD $18,500 wire to ELIGIBLE TO SUBMIT; the board live payment card updated with the rule ids. Verify chain stayed green (8, then 10).
- Clean `dev.sh stop; dev.sh start` on a fresh database kept the audit chain green and accepted new payments.
- No rule id ever appeared on /play.

## Screenshots

`frontend/e2e/screenshots/`: qa-board.png (1920x1080), qa-play.png (390x844), qa-ops.png (1440x900), qa-play-joined.png, qa-play-turn1.png, qa-play-turn2.png, qa-play-turn3.png, qa-board-turn1.png, qa-board-turn2.png, qa-board-turn3.png, qa-board-attack-inject.png, qa-board-attack-mutate.png, qa-board-attack-replay.png, qa-board-attack-self-approve.png, qa-ops-before.png, qa-ops-after.png, qa-ops-approved.png, qa-board-approved.png, qa-play-killed.png, qa-board-killed.png. The isolated smoke run refreshed board.png, board-attack.png, board-debrief.png, play-join.png, play-chat.png, ops.png, ops-tampered.png.

Stack state at the end: `scripts/dev.sh stop` run; SpacetimeDB left running on :3000; `backend/second_key.db` is the fresh one from `--fresh` plus the smoke run.
