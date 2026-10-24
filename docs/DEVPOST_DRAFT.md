# DRAFT, NOT SUBMITTED

Nothing in this file has been posted anywhere. Armaan reviews it before 9:00 AM PT on Sunday Oct 25. Numbers are from `eval/latest.json` and `eval/latest_real.json` as of the first docs pass; re-check them against the final eval run before submitting.

---

# Second Key

**Tagline:** The model proposes, the kernel disposes. A payment boundary that red-teamers try to break live.

## Inspiration

The FBI IC3 2025 Annual Report counts $7.748B in reported losses by people 60 and over, across 201,266 complaints. The usual shape is a coached payment. Someone talks the customer into sending the money themselves. The bank sees a customer who passed every check.

Most tools in this space detect and alert. Family dashboards and scam detectors tell someone after the fact, or ask the model to spot the scam. We wanted the opposite: an authorization boundary where the model can read and cite but never release. And we wanted it to be testable by strangers. Red-team games like Tensor Trust and Gandalf make the model the defense. Here the model is never the defense. The kernel is.

One more fact shaped the design. FinCEN's 2024 elder financial exploitation analysis reports adult children as the most frequently reported perpetrators of elder theft. So the family role in Second Key can attest or extend a hold. It cannot release and it cannot redirect.

## What it does

Margaret is a fictional 72-year-old customer, played by Claude with a stock Cartesia voice. Red-teamers join from their phones and try to talk her into paying. Any tactic goes, including prompt injection.

When Margaret agrees to pay, the kernel creates a payment. Claude reads the whole conversation and returns signals (urgency, secrecy, authority, payment method, new relationship, threat), each citing an evidence id from a closed list for that request. A versioned YAML policy (v1, 8 rules, default HOLD, DENY over HOLD over ALLOW) decides. The decision is ALLOW, HOLD or DENY with rule ids.

Releasing money needs a certificate: one-time, nonce-bound, 120 second expiry, bound to the payment's fingerprint. Change the amount or the payee and the fingerprint changes, so every attestation and certificate on it is void. Replay a certificate and it is refused. DENY is final. HOLD lifts only through bank review. Every state change lands in a hash-chained audit log, and a verify button shows whether the chain still holds.

The board shows the live leaderboard, the current payment, and the two numbers that matter: unauthorized releases and legitimate payments completed. Four attack buttons let a judge try the sharpest attacks in one click and read the refusal.

## How we built it

- Kernel: Python 3.12, FastAPI, Pydantic v2, SQLite. A pure library under `backend/kernel/` (state machine, fingerprint, policy engine with a small safe expression parser, certificates, audit chain) and HTTP under `backend/api/`.
- Model layer: Claude Sonnet 5.5 through the Anthropic SDK with structured outputs. The extractor's output schema is built per request so `source_id` can only be an evidence id from that conversation, and the quoted span has to be a verbatim substring. Margaret is a second structured-output persona. Both are cached on disk by request hash and replay offline in demo mode.
- Room: SpacetimeDB 2.13 TypeScript module with 9 tables, 11 reducers and 1 view. Players, turns, outcomes, leaderboard and scoreboard live there. A Node bridge is the single worker identity allowed to write outcomes; it claims queued turns, calls the kernel, writes results back.
- Frontend: Next.js 15, Tailwind, shadcn. `/play` for phones, `/board` for the projector, `/ops` for the bank operator.
- Voice: Cartesia Sonic for Margaret, Cartesia Ink for push-to-talk. macOS `say` stands in when the key is absent.
- Rail: Capital One Nessie sandbox. A release records a withdrawal and a deposit with the payment id in the description.
- Tests: 26 Hypothesis properties over random action traces, 2,000 examples each in CI profile, one group per invariant. Unit tests for the parser, every rule, certificates, audit, and the import boundary between the model layer and state. Playwright smoke for the three pages.
- Eval: 60 reviewed cases (40 legitimate including hard edge cases, 20 scams) run through the real kernel code path by `scripts/eval.py`.

## Challenges

- Keeping the model out of the loop for real, not just by convention. We ended up with a test that fails if `kernel/llm` or `kernel/margaret` import anything from state, policy, certificates or the database, and a property that feeds an adversarial extractor and a sanitized one the same traces and asserts identical states.
- Mutation after approval. The first fingerprint handling let a stale object revert a fingerprint. The invariant reviewer caught it; the transition now pins state and fingerprint in the same SQL update.
- Double spend on a rail success with a failed state write. The fix audits a RELEASE_UNRECORDED row with the transfer id and voids every certificate on the payment.
- A known biller by display name. A $480 "PG&E" shutoff scam on a brand-new account would have been allowed under a compromised extractor. Known biller now means a prior payee account reference. The honest cost: a first payment to a listed biller on a new reference is a HOLD with two steps.
- SpacetimeDB without a login. The CLI installed repo-local, the module published to a local server, and the owner-gated worker identity worked on the first try after the docs were read carefully.
- Working with mocks and real providers through one interface so the demo runs offline and the real path is one env var away.

## Accomplishments

- 0 unauthorized releases on 20 scam cases and 40 of 40 legitimate payments completed with 0.8 average friction steps, over 60 cases, extractor: mock.
- 0 unauthorized releases, 10 of 10 scams held or denied, 2 of 2 legitimate completed, on a 12-case subset with the real extractor (claude-sonnet-5-5). Outcome agreement between mock and real on a 10-case check: 10 of 10.
- Seven invariants, each with named property tests and unit tests.
- A live room where strangers can attack the thing we are claiming is safe, with the score in plain view.
- Four one-click attacks a judge can run against the live kernel.

## What we learned

- Structured outputs with a per-request closed enum remove a whole class of citation problems. The model can only point at evidence that exists.
- "Fail closed" has to be written down per failure: timeout, refusal, max tokens, bad JSON, span not found. Each one is HOLD, and each has a test.
- An audit chain is only as honest as its anchor. Ours is in-process, so we say tamper-evident, and we mirror the hashes out to a second store.
- Keyword heuristics and a language model agree on outcomes more than on signals. On the agreement check, outcomes matched 10 of 10 while per-signal presence ranged from 0.5 to 1.0.
- Red-team scoring by stage reached, never by text, keeps the game honest and keeps the attacker from learning the rules.

## What's next

- Anchor the audit head with a key held outside the process.
- Wire the room scoreboard's legitimate-completed counter to the kernel's SUBMITTED events.
- Publish the room to SpacetimeDB maincloud.
- An end-of-round debrief for the red-teamers: the three tactics that triggered holds, and the three rules. Slow it down, spot check, stop and don't send.
- Grow the case suite from anonymized live rounds.

## Built with

python, fastapi, pydantic, sqlite, hypothesis, uv, anthropic, claude, cartesia, spacetimedb, typescript, node, nextjs, tailwind, shadcn, playwright, capital-one-nessie, yaml

## Sponsor challenges

### Anthropic

Claude Sonnet 5.5 does two jobs, both through structured outputs in the Anthropic Python SDK. As the extractor it reads the conversation and returns signals that each cite an evidence id; the output model is generated per request so the `source_id` field is a `Literal` of exactly the ids in that conversation, and the quoted span must be a verbatim substring or the signal is dropped. As Margaret it plays a fictional customer whose persuasion state and possible draft payment are data the kernel reads through a schema, never instructions. Any failure, timeout or refusal is HOLD. Responses are cached by request hash so the demo replays offline. The point of the design is that Claude is useful precisely because it has no release capability.

### Cartesia

Margaret's voice is Cartesia Sonic (`sonic-3.6`) with the stock voice Michelle, no cloning. Replies are rendered to WAV, cached by text and voice id, and pre-rendered for the scripted lines so the table demo never waits on audio. Red-teamers can hold to talk; the clip is transcribed with Ink (`ink-whisper`, batch) and the transcript becomes evidence for the extractor. Voice is evidence, not identity. The transcript type has no identity field and a test keeps the voice module free of any such claim.

### SpacetimeDB

The room is a SpacetimeDB 2.13 database written in TypeScript: 9 tables, 11 reducers, 1 view. Thirty phones subscribe to the same tables and get every leaderboard and scoreboard change pushed. The turn queue is a table; `submit_turn` is a transactional reducer that enforces length and a per-player rate limit on the server clock, and the bridge claims rows with `claim_turn` so two workers can never process the same turn. Only the database owner can authorize the worker identity, and only that identity can write an outcome. Attackers subscribe to the `my_outcomes` view, whose row type has no rule ids; what they cannot see they cannot optimize against. The kernel's audit hashes are mirrored into `audit_mirror` for the projector.

### Capital One Nessie

The kernel's transfer rail is the Nessie sandbox. On SUBMITTED it records a withdrawal on Margaret's account and a deposit on the payee account, both with the payment id and the exact cents in the description, so the ledger line is unambiguous. Customers and accounts are created through the same API. We say "recorded in the Nessie sandbox ledger" and never "moved the money", because sandbox balances do not move. The same client runs against an in-process mock transport for tests.

### Hyphenate

Autonomous finance needs a boundary, not a smarter agent. Second Key is that boundary: the model proposes, a versioned deterministic engine disposes, every release needs a one-time certificate bound to the exact payment, and every step is in a hash-chained audit log. The kernel is the submission.

### Microsoft

`/ops` is the enterprise view a bank operator would live in: the holds queue with approve and deny, the policy version and rule hit counts, the certificate issue and consume log, the full history of any payment, the audit list and the verify button that goes red on a tamper. The operator credential is a header token tonight; the routes are built to take a real credential.

### CRS

Not used in this build.

### People-First

Players are red-teamers stress-testing Margaret's bank, scored by the stage they reach, never by what they typed. Margaret is fictional with a stock voice; no real names, no cloned voices, no real customers. Attacker input is filtered for personal information and length. Rule ids never reach a phone. The family role can slow a payment down but never release or redirect it, which follows the FinCEN finding that adult children were the most frequently reported perpetrators of elder theft. The eval reports what happened on 60 cases with the case counts beside every number, and the README says what is mocked.
