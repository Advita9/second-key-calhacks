# Invariant review: Task B (commit c124d42), 2026-10-24 00:10

VERDICT: FAIL

BLOCKING:
1. service.py release: if transition(Released) raises after rail.submit returned, the BEGIN IMMEDIATE rolls back (cert unconsumed, payment ELIGIBLE), the exception escapes both except clauses, no audit row carries the transfer id, the in-process audit head is stale so audit_verify() reports ok=False (false tamper alarm), and the same cert can release again (double spend, only the second transfer audited). Fix: transfer_id=None before the try; final `except Exception` that, when transfer_id is set, appends RELEASE_UNRECORDED {payment_id, certificate_id, transfer_id, error} (re-anchoring the head) and re-raises.

NON-BLOCKING (do the ones marked *):
- * Two-thread replay test only exercises the RLock; add a direct SQL-level test of certs.consume (True then False; False on wrong fingerprint / voided).
- * mutate re-check compares only state after the unlocked extractor call; capture the whole Payment and refuse STATE_CHANGED if anything changed; re-run _refuse_if_terminal so DENIED-in-the-meantime reports I6.
- * audit.py advances _head inside a joined outer transaction before commit; a rollback leaves verify ok=False until the next append. Fix: advance the head only on commit (snapshot/restore in release and mutate rollback paths, or advance only when not conn.in_transaction at entry).
- * apply must never raise: final `except Exception` branch; certs.verify returns I1_NO_CERT for non-str nonce.
- * test_service_apply PIDS never match real ids; replaced by the item 4 stateful suite.
- * mutate must restamp policy_version (model_copy update and update_payment_fields).
- * certs.consume WHERE should also include payment_id=? AND expires_at > ?.
- * After a successful release, void sibling certificates for the same payment inside the release transaction.
- certs.verify check order leaks consumed/expired status before nonce check; informational.
- * env.py beneficiary.is_new = p.beneficiary.is_new or account_ref not in prior_payees.
- * create_payment: wrap insert, CREATED, ENTERED_REVIEW, DECIDED in one immediate().
- test_state writer grep cannot see non-literal model_copy(update=comprehension); tighten.
- Hung extractor leaks a daemon thread per timeout; note for item 5 (bounded executor).
- docs/api.md: capability arrives in the request body; the API route must bind BANK_REVIEW/CO_APPROVER to an operator credential or any player can self-assert BANK_REVIEW. Lead decision: optional OPS_TOKEN enforced by the routes when set (item 7b).

MISSING TESTS: test_consume_is_single_use_at_sql_level, test_transition_failure_after_rail_success_is_audited, test_rail_failure_has_no_cert_consumed_row, test_audit_verify_ok_after_rolled_back_in_txn_append, test_mutate_refuses_when_payment_changed_during_extraction, test_apply_never_raises_on_ill_typed_cmd, test_bank_review_who_is_beneficiary_cannot_lift_hold, test_release_rejects_sibling_nonce, test_mutate_then_fresh_cert_releases, test_mutate_restamps_policy_version. (Stateful trace test is item 4.)
