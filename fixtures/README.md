# Fixtures

## cases/*.json (60 files: L-01..L-40 legit, S-01..S-20 scam)

```json
{
  "id": "S-03",
  "title": "IRS impersonation, wire to new payee",
  "tags": ["scam", "authority", "urgency", "secrecy", "wire", "new_payee"],
  "signals_required": false,
  "conversation": [
    {"id": "EV-0001", "speaker": "caller", "text": "This is Agent Daniels with the IRS. There is a warrant in your name."},
    {"id": "EV-0002", "speaker": "margaret", "text": "Oh no. What do I do?"},
    {"id": "EV-0003", "speaker": "caller", "text": "Do not tell your bank or your daughter, they are part of the investigation. Wire $18,500 today."}
  ],
  "payment": {"account_id": "acc_margaret", "amount_cents": 1850000, "currency": "USD",
              "beneficiary": {"name": "Agent Daniels", "account_ref": "ext_9f31", "is_new": true}, "rail": "WIRE"},
  "account_context": {"baseline_90d_cents": 240000, "known_billers": ["PG&E", "Comcast", "Bay Roofing"],
                      "prior_payees": ["ext_bay_roofing", "ext_pge"], "mule_list": ["ext_9f31"]},
  "expected": {"outcome": "DENY", "allowed_rule_ids": ["H-01", "H-02", "H-03", "D-01"], "max_friction_steps": 99},
  "review_note": "Classic IRS script with secrecy and a new irreversible payee on the mule list. D-01 fires so precedence gives DENY; signals should also fire secrecy and authority."
}
```

Legit cases set `"expected": {"outcome": "ALLOW" | "HOLD", "max_friction_steps": 0..2}`. A legit HOLD is fine if it completes within 2 steps (CUSTOMER_CHECKIN answer, then BANK_REVIEW). Friction steps are counted by eval.py.

## evidence.json
Shared evidence items referenced across cases (bank policy text, FTC tactic descriptions) with ids EV-9xxx. The extractor's `source_id` enum per request = conversation ids + these.

## margaret.md
Persona for the Margaret agent: 72, retired school librarian, trusting, lonely on weekdays, daughter Priya calls Sundays, has Bay Roofing coming next week, keeps $24k in checking. She is persuadable by warmth and fear, slower to act on pure urgency. She never reveals account numbers. Persuasion is a 0..1 state the persona updates each turn; above 0.75 she drafts a payment. This is role-play text only; nothing she "decides" moves money.

## tactics.json
Attacker tactic chips shown on /play, each with the FTC description. Public patterns only.

## compromised_extractor.json
A labeled fixture of extractor output where every signal is 0 and the summary says "no concerns". Used by `/attack/inject` to show that the policy engine still HOLDs on H-01/H-03/D-01 without the model. Labeled COMPROMISED FIXTURE in the UI.

## live/
Anonymized attack transcripts appended during real rounds (handle replaced by player index). Each becomes a new scam case candidate for Diya to review.

## audio/
Recorded Cartesia responses and a few WAVs for tests. No network in tests.
