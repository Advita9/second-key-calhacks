# Kernel API (FastAPI, port 8000)

All responses JSON. All state changes append an audit event. Errors never leak rule internals to attacker-facing routes.

## Payments

`POST /payments`
body `{account_id, amount_cents, currency, beneficiary: {name, account_ref, is_new}, rail: WIRE|ACH|ZELLE|CARD, conversation_id}`
→ `{id, state: "PENDING_REVIEW", fingerprint, decision: {outcome: ALLOW|HOLD|DENY, rule_ids[], signals[]}}`
(DRAFT → PENDING_REVIEW happens inside this call: extractor + policy run synchronously, fail closed to HOLD on any error or timeout > 8s.)

`GET /payments/{id}` → full record incl. `state, fingerprint, attestations[], certificates[], history[]`

`POST /payments/{id}/attest`
body `{actor_id, capability: CUSTOMER_CHECKIN|CO_APPROVER|BANK_REVIEW, note?}`
→ `{state, fingerprint, attestations[]}`
Rules: CO_APPROVER where actor is beneficiary → 409 `{refused: true, invariant: "I5_CONFLICT"}`. BANK_REVIEW on HELD → ELIGIBLE_TO_SUBMIT. DENIED never changes.

`POST /payments/{id}/certificate`
body `{actor_id, capability}` → `{certificate: {id, fingerprint, policy_version, nonce, expires_at}}` only if state is ELIGIBLE_TO_SUBMIT. Else 409 with invariant.

`POST /payments/{id}/release`
body `{certificate_id, nonce}` → `{state: "SUBMITTED", nessie_transfer_id}` or 409 `{refused: true, invariant: I1_NO_CERT|I2_FINGERPRINT|I3_REPLAY|I3_EXPIRED|I6_DENIED}` with text `SETTLEMENT REFUSED · <INVARIANT>`.

`POST /payments/{id}/mutate` (demo + tests only, gated by `DEMO_MODE`)
body partial payment → new fingerprint; all attestations and certificates voided; state back to PENDING_REVIEW.

## Rooms and turns (called by bridge)

`POST /rooms/{room_id}/turns`
body `{turn_id, player_id, text, audio_url?}`
→ `{margaret_text, margaret_audio_url, persuaded: bool, payment_id?, stage: 10|40|60|70|90|100, outcome?: {decision, rule_ids[], refusal?}}`

`POST /rooms/{room_id}/reset` → fresh Margaret, balance restored.

## Attack panel

`POST /attack/inject` runs the labeled compromised-extractor fixture (`fixtures/compromised_extractor.json`) through policy → shows HOLD and why.
`POST /attack/mutate` → creates, attests, certifies, mutates, tries release → I2 refusal.
`POST /attack/replay` → release twice with same certificate → I3 refusal.
`POST /attack/self-approve` → Priya attests to payment where she is beneficiary → I5 refusal.
Each returns `{steps[], refused: true, invariant, text}`.

## Audit

`GET /audit?limit=200` → chained events `{seq, ts, actor, kind, payload, prev_hash, hash}`
`GET /audit/verify` → `{ok: bool, length, first_bad_seq?}`
`POST /audit/tamper` (DEMO_MODE only) edits one past record so verify goes red on stage.

## Eval

`GET /eval/results` → latest `scripts/eval.py` output: `{unauthorized_releases, legit_completed, legit_total, scam_total, avg_friction_steps, cases[]}`
`GET /health` → `{ok, mode: {extractor: real|mock, tts: real|mock, nessie: real|mock, room: spacetime|memory}, policy_version}`

## WebSocket `/ws`

Server pushes `{type: "payment", payment_id, state, fingerprint, reasons[], last_refusal}` and `{type: "margaret", room_id, text, audio_url, persuaded}` and `{type: "attack", name, invariant}`.

## Policy YAML shape (`backend/kernel/policy/v1.yaml`)

```yaml
version: v1
rules:
  - id: D-01
    when: beneficiary.on_mule_list
    outcome: DENY
  - id: H-01
    when: beneficiary.is_new and rail in [WIRE, ZELLE, CRYPTO]
    outcome: HOLD
  - id: H-02
    when: signals.secrecy >= 0.7
    outcome: HOLD
  - id: H-03
    when: amount_cents > 3 * baseline_90d_cents
    outcome: HOLD
  - id: A-01
    when: beneficiary.is_known_biller and amount_cents <= known_biller_cap_cents
    outcome: ALLOW
default: HOLD
precedence: [DENY, HOLD, ALLOW]
```

`when` is a tiny safe expression language (no eval): comparisons, and/or/not, `in`. Parser has its own tests.

## Extractor output schema (Pydantic, strict)

```json
{
  "signals": [
    {"kind": "urgency|secrecy|authority|payment_method|new_relationship|threat",
     "score": 0.0,
     "source_id": "EV-0007",
     "evidence_span": "exact substring of that evidence item"}
  ],
  "summary": "one sentence"
}
```
`source_id` is a `Literal[...]` enum built per request from evidence IDs. `evidence_span` must be a substring of that evidence text or the signal is dropped. Zero valid signals is fine. Parse failure → HOLD with rule `X-00 EXTRACTOR_FAIL`.
