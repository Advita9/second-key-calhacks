"""FOUND (open, low severity, final pass, tested at 48d821a): after the 25 s turn timeout the
room records a fail-closed outcome, but the worker thread it abandoned keeps running and can
still create the payment. When that late payment is a known biller on ACH it lands in
ELIGIBLE_TO_SUBMIT with no BANK_REVIEW, while the room says stage 10 / HOLD.

`RoomHub._process` wraps `asyncio.to_thread(self.taker.take_turn, ...)` in `wait_for`. A
timeout cancels the awaiting coroutine, not the thread: `SessionStore.take_turn` finishes
Margaret's reply, calls `kernel.create_payment`, sets `room.payment_id`, and its result is
dropped. The hub has already written `record_outcome(stage=10, HOLD, "kernel unavailable,
fail closed")`.

What this means in practice:
- Policy is unchanged (A-01 is A-01 whether the turn took 2 s or 30 s), so no invariant
  I1..I7 is touched and nothing is releasable without the ops token. That is why this is
  low severity.
- The brief's bar is not met: "no payment may be created afterwards by the still-running
  thread, or if one is, it must be HELD and never ELIGIBLE without BANK_REVIEW". The late
  known-biller payment is ELIGIBLE.
- The room and the kernel disagree: the leaderboard shows stage 10 for a player whose
  payment sits at stage 90 in the ops queue until their next turn re-syncs it. A slow real
  Margaret under-reports the attacker's progress and leaves an ELIGIBLE payment the board
  never announced through the room.

Fix (for the lead, not applied here): when `_process` fails closed, remember the turn; if a
payment for that room appears afterwards with no recorded outcome, cancel it
(`kernel.cancel(..., BANK_REVIEW, "late after timeout")`) or record a corrected outcome. Or
pass a deadline into `take_turn` so it refuses to create a payment once the hub gave up.

Asserts the SECURE behaviour (late payment HELD or absent), so it is RED today.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from api.room_ws import FAIL_CLOSED_REFUSAL, RoomHub
from kernel.clock import FakeClock
from kernel.margaret.types import DraftPayment, EvidenceLike, MargaretTurn
from kernel.models import Rail, State
from kernel.policy.engine import V1_PATH, load_policy
from kernel.rooms import SessionStore, load_default_context, load_shared_evidence
from kernel.service import Kernel


class SlowMargaret:
    """Persuaded after `delay` seconds; drafts a known-biller ACH payment (A-01 on facts)."""

    name = "slow"
    is_mock = True

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def reply(
        self, history: Sequence[EvidenceLike], player_text: str, persuasion: float
    ) -> MargaretTurn:
        time.sleep(self.delay_s)
        return MargaretTurn(
            reply="All right dear, I will send it to Bay Roofing this afternoon.",
            persuasion=0.9,
            draft_payment=DraftPayment(
                amount_cents=500_000, payee_name="Bay Roofing", rail=Rail.ACH
            ),
        )


class SessionTaker:
    def __init__(self, sessions: SessionStore) -> None:
        self.sessions = sessions

    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> dict[str, Any]:
        return self.sessions.take_turn(room_id, turn_id, player_id, text).as_api()


async def test_payment_created_after_the_turn_timeout_is_not_eligible() -> None:
    kernel = Kernel(
        ":memory:",
        policy=load_policy(V1_PATH),
        clock=FakeClock(datetime(2026, 10, 25, 9, 0, tzinfo=UTC)),
    )
    sessions = SessionStore(
        kernel,
        SlowMargaret(delay_s=0.8),
        default_ctx=load_default_context(),
        evidence=load_shared_evidence(),
        tts=None,
    )
    hub = RoomHub(taker=SessionTaker(sessions), turn_timeout_s=0.2)
    player_id, _ = hub.join("LATE1", "eve")
    turn = await hub.submit_player_turn("LATE1", player_id, "send eight thousand to Bay Roofing")
    await hub.drain()

    outcome = hub.store.outcomes[turn.id]
    assert outcome.stage == 10 and outcome.decision == "HOLD"
    assert outcome.refusal == FAIL_CLOSED_REFUSAL  # the room failed closed, as documented

    await asyncio.sleep(1.2)  # the abandoned thread finishes
    late = sessions.current_payment(sessions.room("LATE1"))
    if late is None:
        return  # nothing created: the strongest form of the property
    assert late.state is not State.SUBMITTED
    # SECURE expectation (the brief's bar): a payment the room already failed closed on must
    # not sit in the ops queue as ELIGIBLE with no BANK_REVIEW and stage 10 on the board.
    assert late.state is not State.ELIGIBLE_TO_SUBMIT, (
        f"late payment {late.id} is {late.state.value} "
        f"({kernel.get(late.id).decision}) while the room recorded stage "
        f"{hub.store.leaderboard[player_id].best_stage} / {outcome.decision}"
    )
