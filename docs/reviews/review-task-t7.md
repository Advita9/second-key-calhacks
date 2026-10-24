# Invariant review: T7 API routes, rooms, nessie (commit b89ed2c), 2026-10-24 02:05

VERDICT: FAIL

BLOCKING:
1. api/routes/attack.py: /attack/replay and /attack/mutate call issue_certificate, release, mutate with no ops guard; with OPS_TOKEN set, money moves on the rail without a token. Fix: router-level `dependencies=[Depends(deps.ops_guard)]`; board sends X-Ops-Token.
2. api/hub.py + api/room_ws.py: payment events (reasons, fingerprint, last_refusal) and attack events are broadcast to every subscriber regardless of role; role is self-declared (snapshot?role=ops with no token returns the ops view). Fix: attacker sockets receive only room and margaret events; board/ops roles require X-Ops-Token or ?token= when OPS_TOKEN is set.

NON-BLOCKING (all to be done):
- /attack/mutate ignores DEMO_MODE; mirror the gate.
- Attacks leave ELIGIBLE payments in the ops queue; cancel at the end of each attack. docs/api.md says the mutate attack attests; align.
- rooms.py: account_ref = "ext_" + slug(payee_name): the attacker's typed name becomes the ref; "send $8,000 to Rosa" -> ext_rosa (prior payee) -> A-01 ALLOW stage 90. Fix: explicit name -> ref directory in AccountContext (exact match, known billers only); anything else mints ext_new_<sha8>. balance_cents never checked; enforce or drop.
- /rooms/{room}/turns JSON path is unauthenticated, returns full_outcome, no length/rate limits, spoofable player_id. Gate with ops/bridge token when set; multipart path returns public_outcome; cap 400 chars.
- SessionStore.normalize accepts any string; use RoomStore.normalize_code (3-16 [A-Z0-9-]) else 400.
- TURN_TIMEOUT_S 8.0 below the real-mode budget (Margaret 12 s + extractor + TTS); raise to ~25 s.
- reset: hub.changed() from a sync route is not loop-safe; also cancel the room's open payment on reset.
- POST /payments accepts caller account_context/conversation with no credential; require ops token for bodies with account_context when OPS_TOKEN set.
- KeyError handler masks bugs as 404; raise a dedicated NotFound.
- nessie.py: non-2xx (3xx) must be RailError; silence httpx INFO logger in the real branch (URL carries ?key=).
- hub.publish may raise RuntimeError inside finally blocks; wrap.
- rooms.py TTS ThreadPoolExecutor never shut down; add close() and call from deps.reset().

MISSING TESTS: test_attack_routes_require_ops_token_when_set, test_attacker_ws_never_receives_payment_or_attack_events, test_board_ops_roles_need_token_when_set, test_attack_mutate_404_when_demo_off, test_attacks_leave_nothing_eligible, test_room_payee_name_cannot_mint_known_ref, test_turns_route_limits, test_hub_turn_timeout_covers_real_budgets, test_nessie_non_2xx_is_rail_error, test_httpx_log_never_contains_key, test_post_payments_account_context_requires_ops_token_when_set, test_reset_cancels_open_room_payment.
