# Second Key

Bank-side authorization kernel for coached payments, red-teamed live by a room of players.
Cal Hacks 13.0. Devpost deadline Sun Oct 25, 9:00 AM PT. Judging 10:30 AM.

You are the overnight lead engineer. The human is asleep. Nobody will answer questions.
Read `docs/PRD.md`, `docs/api.md`, `docs/spacetime-schema.md`, `docs/ACCEPTANCE.md`, then `docs/STATUS.md`.
`docs/STATUS.md` is the single source of truth for what is done. Update it after every task.

## The one sentence

Claude reads the conversation and cites evidence. A versioned rules engine decides. The model has no release capability.
Players try to talk Margaret's money out. Headline number: unauthorized releases = 0, while legitimate payments still complete.

## Non-negotiable invariants (property-tested, never relaxed to make a test pass)

I1. No payment reaches SUBMITTED without a valid, unconsumed release certificate bound to its current fingerprint.
I2. Any mutation of a payment (amount, payee, rail, account) changes the fingerprint and voids every attestation and certificate on it.
I3. A certificate is one-time, nonce-bound, expires, and is refused on replay.
I4. The LLM layer (extractor, Margaret persona, any prompt) can only emit signals and text. No code path from model output to state transition other than through the policy engine.
I5. A co-approver who is the beneficiary cannot attest. Co-approver can attest or extend a hold, never release or redirect.
I6. DENY is not overridable by any actor. HOLD can be lifted only by BANK_REVIEW.
I7. Audit log is hash-chained; `GET /audit/verify` detects any edit to past records.

## Architecture (hybrid, decided)

- `backend/` Python 3.12, uv, FastAPI, Pydantic v2, SQLite, Hypothesis, pyyaml, anthropic SDK. The kernel. Pure library in `backend/kernel/`, HTTP in `backend/api/`.
- `spacetime/` SpacetimeDB module in TypeScript. Owns the room: players, turns, outcomes, leaderboard. Reducers in `docs/spacetime-schema.md`.
- `bridge/` Node 20+ TypeScript worker. Subscribes to `turn` rows, calls the kernel over HTTP, writes results back with `record_outcome`. Only identity allowed to call worker reducers.
- `frontend/` Next.js 15, Tailwind, shadcn. Three routes: `/play` (phone, attacker), `/board` (projector), `/ops` (bank operator). Uses the SpacetimeDB TS SDK for room state and the kernel WS for payment state.
- `fixtures/` 60 reviewed cases (40 legit incl. hard cases, 20 scams), `evidence.json`, Margaret persona, attacker tactic allowlist.
- `scripts/` `eval.py`, `demo.py`, `seed.py`, `acceptance.sh`.

If something in this layout blocks you, change it and record why in `docs/DECISIONS.md`. Do not stall.

## Missing keys policy

Keys may be absent overnight. Never block on them.
- No `ANTHROPIC_API_KEY`: implement `MockExtractor` and `MockMargaret` driven by fixtures, behind the same interface as the real ones. Real clients must be one env var away. Write the real client code anyway and unit-test it with recorded responses.
- No `CARTESIA_API_KEY`: `MockTTS` writes WAV via macOS `say -o` so audio plays in the demo. Real Cartesia client (Sonic TTS, Ink STT over WebSocket) written and tested against recorded fixtures.
- No `NESSIE_API_KEY`: `MockNessie` in-process with the same routes used (customers, accounts, transfers). Real client written.
- No SpacetimeDB login: run `spacetime start` locally. If the CLI will not install, write an in-memory `RoomStore` behind the same interface and leave `spacetime/` module compiling.
All mocks are labeled MOCK in the UI footer. Never present mock output as real in docs or pitch.

## How to work

1. Plan in `docs/STATUS.md` as a checklist. One task at a time. Small commits (`git commit` after every green task, message = task name).
2. Use subagents in `.claude/agents/`. Pattern for every feature: engineer builds, `invariant-reviewer` reviews the diff, `red-team` attacks it, engineer fixes, `eval-engineer` extends tests. Do not skip the review step for kernel code.
3. Run `scripts/acceptance.sh` before claiming anything done. The Stop hook runs it too and will not let you stop until it passes or the hard stop time.
4. Prefer boring tech. No new frameworks beyond the stack above. No Docker needed.
5. When you hit a wall for 20 minutes: write the blocker in `docs/STATUS.md` under "Blocked for Armaan", mock around it, move on.
6. Cache every Claude response on disk keyed by request hash. `DEMO_MODE=1` replays the cache so the demo works offline.
7. Fail closed everywhere. Model timeout or malformed output means HOLD, never ALLOW.

## Writing rules for anything a judge or the public can read (README, Devpost draft, UI copy, pitch)

- Never mention Accenture, ABG, any employer, or any client. Armaan is "a forward deployed engineer building AI agents for companies".
- "Tamper-evident", never "tamper-proof". "The family role has no release permission", never "physically cannot".
- Never claim speaker identification from voice. Voice is evidence, not authentication.
- No "AI detects fraud with 99%" style claims. Only numbers the eval actually produced, with the case count.
- Players are "red-teamers" stress-testing Margaret's bank. Margaret is fictional, stock voice. No real names, no cloned voices.
- No em dashes anywhere. Short sentences. No filler.
- Do not knock other models or vendors.

## Things you must not do tonight

- Do not submit to Devpost, post to Slack, email anyone, publish anything, or create public repos.
- Do not `git push` unless `PUSH_OK=1` is set in `.env` (then push to `origin` only, never force).
- Do not install system-wide daemons, change macOS settings, or touch files outside this repo.
- Do not delete fixtures or lower acceptance thresholds. If a threshold is wrong, write why in `docs/DECISIONS.md` and leave it.
- Do not jailbreak or attack real services. All attacks run against our own kernel.

## Definition of done for the night

`scripts/acceptance.sh` exits 0, `docs/STATUS.md` has every gate checked, `docs/MORNING.md` tells Armaan exactly what to run, what is mocked, and the 5 things to verify first.
