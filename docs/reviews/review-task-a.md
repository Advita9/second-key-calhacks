# Invariant review: Task A (commit db6c6d6), 2026-10-23 23:55

VERDICT: FAIL

BLOCKING:
1. policy/env.py is_known_biller name OR ref. (Fixed in c124d42: ref only, plus name_on_biller_list.)
2. db.py insert_payment writes p.state verbatim; SUBMITTED insertable with no audit. Fix: force/require DRAFT.
3. state.py transition UPDATE pins only state and rewrites fingerprint from the handle; stale handle can revert F2 to F1. Fix: WHERE id=? AND state=? AND fingerprint=?; set fingerprint only on Mutated.
4. policy/engine.py precedence validation only requires ALLOW last; [HOLD, DENY, ALLOW] loads and overrides DENY. Fix: require exactly (DENY, HOLD, ALLOW).
5. state.py Released edge never checks the certificate table. Fix: inside the immediate block, SELECT a certificate row with id=ev.certificate_id, payment_id=p.id, fingerprint=p.fingerprint, voided_at IS NULL, consumed_at IS NOT NULL; else IllegalTransition.

NON-BLOCKING (do the ones marked *):
- * db.py immediate(): per-connection RLock inside immediate() so no caller can forget it (reproduced lost audit rows under threads without the kernel lock).
- * audit.py append: compare DB tail to the in-process anchor before INSERT; raise on mismatch.
- audit anchor is in-process only; record in DECISIONS and keep "tamper-evident" wording.
- * Rename Submitted event / SUBMITTED audit kind (DRAFT -> PENDING_REVIEW) to EnteredReview / ENTERED_REVIEW so release counts are not polluted.
- * Mutated.new_fingerprint must be validated (pattern ^[0-9a-f]{64}$); certificate_id/transfer_id min_length=1. Mutated payload should carry from_fingerprint; nest event fields under "event".
- * engine.decide: catch Exception (not only EvalError) per rule, log the rule id, HOLD + X-01.
- * engine.load_policy: smoke-evaluate each rule against a sample env and require bool.
- * env.py: beneficiary.is_new = p.beneficiary.is_new or account_ref not in prior_payees (never trust caller alone).
- * expr.py: reject non-finite numeric literals (inf) with ParseError.
- test_boundary overstated; strengthen with call-site test (Decided( only in state.py and service.py, outcome from Decision.outcome). Add kernel.policy/audit/fingerprint to the forbidden list for kernel/llm and grep for importlib/__import__.
- test_state grep too loose; tighten patterns (model_copy(, model_construct(, setattr(, __dict__, REPLACE INTO payment, INSERT INTO payment outside db.py, State.<non-DRAFT> outside state/models/db).
- test_engine allow-only test name mismatch; fix with amount_cents > 10_000_000 fixture.
- docs/api.md: add CRYPTO to rail and the 8 rules.

MISSING TESTS: see the reviewer transcript list; the engineer adds every one marked in the fix task.
