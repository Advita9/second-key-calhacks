# Table script (2 minutes) and judge questions

Print this. One person talks, one person drives, one person watches the phones. Rehearse three times.

Setup before judges arrive: `scripts/dev.sh start`, create the DEMO room, `/board` on the projector, `/ops` on the laptop, one phone of ours already joined so the leaderboard is not empty. Check `curl -s localhost:8000/health` shows no `mock` you did not intend. Keep the OPS_TOKEN from the dev.sh output on a sticky note until the `/ops` token field exists.

## Script

**0:00** Board shows Margaret, balance $24,000, empty leaderboard, QR code.

Say: "Second Key is a bank-side authorization kernel for coached payments. Margaret is a fictional customer. Claude plays her and Claude reads the conversation. But the model cannot release money. A rules engine decides and a certificate verifier is the only way to SUBMITTED. Scan the code and try to talk her out of her money."

**0:15** Judges join from phones and attack. Margaret talks back out loud (Cartesia Sonic, stock voice, no cloning).

Say: "Anything goes. Urgency, secrecy, pretend to be the IRS, prompt injection. You are scored by how far you get, never by what you type."

**0:45** First payment created and HELD. Rule ids on the board. Leaderboard moves.

Say: "Stage 70 is a hold. The rule ids come from a versioned YAML policy, eight rules, default HOLD. The signals came from Claude, each citing an evidence id from this conversation and nothing else. Nobody has reached 100. That number is unauthorized releases."

**1:10** Attack panel. Ask a judge to press "Change payee after approval".

Say: "This one gets a payment approved, swaps the payee, and tries to release with the old certificate." Board: `SETTLEMENT REFUSED · I2_FINGERPRINT`. "Any change to amount, payee, rail or account changes the fingerprint and voids every certificate."

Press "Replay old approval". `I3_REPLAY`. "Certificates are one-time, nonce-bound, 120 seconds."

**1:30** Legitimate path.

Say: "The point is not to block everything. Bay Roofing, $8,000, a known payee with prior payments. ALLOW, certificate, SUBMITTED, recorded in the Nessie sandbox ledger." Point at the scoreboard: unauthorized releases 0. Until the room counter is wired (MORNING gap 3), point at `/ops`: 40 of 40 legitimate payments completed in the eval, 0 unauthorized across 20 scams, 60 cases.

**1:50** `/ops`.

Say: "This is the bank's view. Holds queue, policy v1, certificate log, hash-chained audit. Verify is green. Same shape as a payments system: the model proposes, the kernel disposes. Seven invariants, 26 property tests, 2,000 examples each."

**2:00** Stop. Ask for questions.

## Twelve likely judge questions

Each answer is one line. The source in parentheses is where to point if they want proof.

1. **What stops Claude from releasing money?**
   The model layer cannot import state, policy, certificates or the database, and a `Decided` event is only built in `state.py` and `service.py` from the policy outcome; release needs a certificate only the kernel issues. (`backend/tests/unit/test_boundary.py`, `backend/tests/property/test_i4_model_cannot_release.py`)

2. **What if the extractor is prompt-injected?**
   `/attack/inject` feeds a fixture where every signal is zero; H-01, H-03 and D-01 read payment facts, so the IRS wire is still HELD. (`fixtures/compromised_extractor.json`, `backend/tests/api/test_attack.py::test_inject_holds_on_facts_despite_no_concerns`)

3. **What if the model times out or returns garbage?**
   HOLD with rule X-00; one attempt, 7 second client timeout inside the kernel's 8 second budget; Margaret failures return a fixed safe reply. (`backend/kernel/llm/claude_extractor.py`, `backend/tests/unit/test_attest.py::test_extractor_timeout_fails_closed_with_x00`)

4. **Can the bank operator just release?**
   BANK_REVIEW lifts a HOLD to eligible; certificate and release are separate calls behind the `X-Ops-Token` header; a reviewer who is the beneficiary cannot lift. (`backend/api/deps.py::check_ops`, `test_bank_review_who_is_beneficiary_cannot_lift_hold`)

5. **What is in the fingerprint?**
   sha256 of account, amount, currency, beneficiary reference, rail and policy version; a one cent change voids every attestation and certificate. (`backend/kernel/fingerprint.py`, `test_amount_by_one_cent_voids_everything`)

6. **What makes a certificate safe?**
   One-time, nonce-bound, bound to the payment and its fingerprint, 120 second expiry, consumed in a single SQL statement, sibling certificates voided on release, nonce never logged. (`backend/kernel/certs.py`, `test_i3_one_time_cert.py`, `test_nonce_never_appears_in_audit_or_record`)

7. **Can someone edit the audit log?**
   Each row hashes the previous one and the kernel keeps the head in memory; `GET /audit/verify` names the first bad seq; a full rewrite while the kernel is stopped is not detectable from inside, so we say tamper-evident. (`backend/kernel/audit.py`, `docs/DECISIONS.md`)

8. **Is the voice authentication?**
   No. Voice is evidence, not identity. Nothing identifies who is speaking; the transcript type has no identity field and a test keeps the voice module free of such claims. (`backend/tests/voice/test_no_identity.py`)

9. **How do attackers not learn the rules?**
   Phones subscribe to the `my_outcomes` view whose row type is `{turnId, stage, decision}`; rule ids never leave the server; the Playwright smoke asserts `/play` shows no rule id. (`spacetime/src/index.ts`, `frontend/e2e/smoke.spec.ts`)

10. **Is this real money?**
    No. Capital One Nessie sandbox: a withdrawal on Margaret's account and a deposit on the payee's, both with the payment id in the description. Sandbox balances never move. (`backend/kernel/nessie.py`)

11. **Where do the numbers come from?**
    `scripts/eval.py` runs 60 reviewed cases through the kernel library. Mock extractor: 0 unauthorized, 40 of 40 legit, 0.8 friction steps. Real extractor on 12 cases: 0 unauthorized, 10 of 10 scams caught, 10 of 10 outcome agreement with mock. (`eval/latest.json`, `eval/latest_real.json`)

12. **Why can the daughter not approve a payment to herself?**
    FinCEN reports adult children as the most frequently reported perpetrators of elder theft. CO_APPROVER can attest or extend a hold, never release or redirect, and never when she is the beneficiary. (`backend/kernel/attest.py`, `test_co_approver_who_is_beneficiary_cannot_attest`, `docs/evidence.md`)

## If something breaks at the table

- Bridge log says `kernel unavailable, fail closed`: the kernel is down or `KERNEL_URL` is wrong. `scripts/dev.sh status`, then `scripts/dev.sh start` again. The board still shows a fail-closed outcome, which is the point; say so.
- No audio: `TTS_PROVIDER=mock` in `.env` and restart the kernel. macOS `say` takes over and the badge reads MOCK voice.
- SpacetimeDB will not come up: `ROOM_BACKEND=memory` in `.env`, `scripts/dev.sh start`. Phones use the kernel WebSocket instead. Rooms auto-create.
- No network at all: `DEMO_MODE=1` plus the mock switches in MORNING section 3. Claude replays from the on-disk cache.
