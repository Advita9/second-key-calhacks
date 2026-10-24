# STATUS (source of truth, update after every task)

Last updated: 2026-10-24 09:40 PDT
Current task: done. Acceptance GREEN, tagged overnight-2 (overnight-1 is the 07:18 state). Nothing running. Next for the team: docs/MORNING.md.
Iteration: 11

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
- [x] 14. Final: full acceptance green, `git log` clean, tag `overnight-1`.

## Blocked for Armaan
(agent lists anything only a human can do: keys, logins, decisions)
- 04:45 rate limit interrupted six agents; all resumed at 07:25 and landed by 09:00 (see docs/MORNING.md READ THIS FIRST, updated block). Final red-team pass found six more issues, all fixed (backend/tests/redteam/test_found_*.py, FOUND then FIXED docstrings).
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
