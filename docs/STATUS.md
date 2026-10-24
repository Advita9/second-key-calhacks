# STATUS (source of truth, update after every task)

Last updated: 2026-10-24 07:16 PDT
Current task: final acceptance run, tag overnight-1. Session rate limit at 04:45 interrupted six follow-up agents (see Blocked for Armaan).
Iteration: 8

## Gates (from docs/ACCEPTANCE.md)
- [x] G1 Kernel library
- [x] G2 Kernel API
- [x] G3 Eval
- [x] G4 Room
- [x] G5 Frontend
- [x] G6 Voice
- [x] G7 Demo mode
- [x] G8 Docs for the morning

## Build order (do in this order; each line is one commit)
- [x] 0. Repo scaffold: uv project, Next.js app, spacetime module, bridge, .env loading, `make dev` / `scripts/dev.sh` that starts everything.
- [x] 1. Kernel domain: Payment, fingerprint (sha256 of account, amount, currency, beneficiary ref, rail, policy version), state machine, audit chain.
- [x] 2. Policy engine: YAML v1, safe expression parser, precedence, tests.
- [x] 3. Certificates and release verifier. Invariants I1, I2, I3, I5, I6 as unit tests.
- [x] 4. Hypothesis property tests over random action traces for I1 to I7. Review by invariant-reviewer, attack by red-team.
- [x] 5. Extractor interface + MockExtractor + real Claude extractor with closed-world source_id enum and span check. Recorded-response tests.
- [x] 6. Margaret persona: MockMargaret (fixture-scripted) + real Claude persona. Persuasion state. Fail closed.
- [x] 7. FastAPI routes per docs/api.md, WS, audit endpoints, attack panel, mutate/tamper under DEMO_MODE. Nessie client + mock.
- [x] 8. Fixtures: 60 cases (Diya's spec: 40 legit incl. 10 hard, 20 scams), evidence.json, mule list, known billers, baselines. eval.py. Hit G3.
- [x] 9. SpacetimeDB module + bridge. Fallback RoomStore if blocked. Hit G4.
- [x] 10. Frontend /board, /play, /ops. Playwright smoke. Hit G5.
- [x] 11. Voice: MockTTS via `say`, Cartesia clients, push-to-talk. Hit G6.
- [x] 12. Demo mode, LLM cache, demo.py. Hit G7.
- [x] 13. README, MORNING.md, DEVPOST_DRAFT.md, DECISIONS.md. Hit G8.
- [ ] 14. Final: full acceptance green, `git log` clean, tag `overnight-1`.

## Blocked for Armaan
(agent lists anything only a human can do: keys, logins, decisions)
- 04:45 session rate limit terminated six in-flight agents. Their briefs (dispatched, not landed):
  1. frontend: /play must use the SpacetimeDB client in spacetime mode so the bridge's fail-closed outcome shows when the kernel dies; 35 s client timeout; join-wipe bug; attack 404 copy; exclude origin=attack from legit count and balance; Playwright on ports 8001/3002; devIndicators off; board clipping; seed live card from GET /payments; ops rule-hit counter; "Run scripted attack" button. (QA_REPORT blockers 1, 3; rough 1, 5 to 11.)
  2. api: `POST /rooms/{room}/scripted-attack` (ops-gated, runs the proven 4-line script from scripts/demo.py through SessionStore); attack payments `conversation_id = attack:<name>` and `origin` field on payment dicts.
  3. bridge: count a SUBMITTED payment as legit only when origin is ops (never attack).
  4. kernel Task F: persist decisions and transcripts in SQLite (holds queue keeps rule ids across restart); scripts/demo.py sends X-Ops-Token under --real and prints only the kernel's refusal text; `LLM_CACHE_MODE=auto|replay|live` (today: DEMO_MODE=1 plus LLM_CACHE_WARM=1 gives the same behaviour).
  5. red-team final pass on role-scoped WS, tokens, payee directory, sidecar anchor (first pass: 48 regressions green, 3 findings found and fixed).
  6. docs: DEVPOST_DRAFT.md and TABLE_SCRIPT.md refresh (README.md and this file were refreshed; MORNING.md has a READ THIS FIRST block).
- Maincloud publish needs `spacetime login` (docs/SPACETIME_NOTES.md). Cartesia promo CARTESIACALHACKS applied in play.cartesia.ai billing.
- Devpost prize text for "Best Use of SpacetimeDB" could not be fetched (403); paste it into docs/PRD.md.

## Key status at 22:05
- ANTHROPIC_API_KEY present. CARTESIA_API_KEY present (TTS_PROVIDER=cartesia). NESSIE_API_KEY present. PUSH_OK=1.
- spacetime CLI not installed at start; install attempted overnight.

## Decisions made tonight
(one line each, details in docs/DECISIONS.md)
- SpacetimeDB CLI installed repo-local at .tools/spacetime; local server works without spacetimedb.com login.
- Nessie base URL is https; transfers modelled as withdrawal + deposit; sandbox never moves balances.
- Margaret voice: Cartesia stock voice Michelle, sonic-3.6, no cloning.
- Known-biller ALLOW requires account_ref match; name match alone never allows (L-33 now HOLD).
- S-03 expects DENY (mule list, D-01 wins precedence); API scenario A uses its own context for HOLD + H-01.
- Scenario B baseline is 300000 cents so $8,000 Bay Roofing does not trip H-03.
