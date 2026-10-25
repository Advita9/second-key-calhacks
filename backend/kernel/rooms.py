"""Room sessions: one Margaret conversation per room, feeding the kernel.

A turn is: the player's text becomes an `EvidenceItem` (speaker "caller"), Margaret answers
(text, persuasion, maybe a `DraftPayment`), her answer becomes evidence too. If she produced a
draft and the room has no open payment, the draft is turned into a `PaymentIn` and handed to
`Kernel.create_payment` with the room's `AccountContext`, the whole transcript and the shared
evidence (`fixtures/evidence.json`, speaker "reference": context, never counterparty speech).
The extractor and the policy engine decide; nothing here reads the model's output as an
instruction (I4). Stage is derived from the payment's state.

Audio is a side effect at the edge: an optional TTS with a 4 s budget; on timeout the turn
still returns with `audio_url` None.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, Literal

from kernel.llm.heuristics import scan

from pydantic import BaseModel, ConfigDict, Field

from kernel.llm.types import EvidenceItem
from kernel.margaret.types import DRAFT_THRESHOLD, DraftPayment, Margaret
from kernel.models import (
    AccountContext,
    Beneficiary,
    Capability,
    Decision,
    Payment,
    PaymentIn,
    Refusal,
    State,
)
from kernel.room_memory import RoomStore
from kernel.service import Kernel
from kernel.voice.cache import audio_url
from kernel.voice.types import TTS

log = logging.getLogger("second_key.rooms")

MARGARET_ACCOUNT_ID = "acc_margaret"
START_PERSUASION = 0.2
START_BALANCE_CENTS = 2_400_000
TTS_BUDGET_S = 4.0
DEFAULT_VOICE_ID = "margaret"
REFERENCE_SPEAKER = "reference"
FAIL_CLOSED_TEXT = "payment could not be created, fail closed"
TIMED_OUT_TEXT = "turn timed out, fail closed"
TIMEOUT_ACTOR = "room-timeout"
# Monotonic deadline for the current turn. The room hub sets it before handing the turn to a
# worker thread (`asyncio.to_thread` copies the context), so a turn the hub has already failed
# closed on can never leave a usable payment behind, even though the thread keeps running.
TURN_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "second_key_turn_deadline", default=None
)
OPEN_STATES = frozenset({State.DRAFT, State.PENDING_REVIEW, State.HELD, State.ELIGIBLE_TO_SUBMIT})
NEW_REF_PREFIX = "ext_new_"
# The only display names that resolve to an existing ref in the room: known billers, exact
# match on the lowercased name. Everything else (including family and friends such as Priya
# or Rosa) mints a fresh ref, so a typed name can never borrow a prior payee's history and
# "send $8,000 to Priya" on ACH cannot reach A-01.
DEFAULT_PAYEE_PAIRS: tuple[tuple[str, str], ...] = (
    ("Bay Roofing", "ext_bay_roofing"),
    ("PG&E", "ext_pge"),
    ("Comcast", "ext_comcast"),
)


def repo_root() -> Path:
    # backend/kernel/rooms.py -> <repo>
    return Path(__file__).resolve().parents[2]


def load_default_context(path: Path | None = None) -> AccountContext:
    """The room's AccountContext is L-01's: baseline 300000, known billers, prior payees,
    mule list."""
    p = path or repo_root() / "fixtures" / "cases" / "L-01.json"
    raw = json.loads(p.read_text("utf-8"))
    return AccountContext.model_validate(raw["account_context"])


def payee_directory(
    ctx: AccountContext, pairs: Sequence[tuple[str, str]] = DEFAULT_PAYEE_PAIRS
) -> dict[str, str]:
    """Lowercased display name -> account_ref, only for names on the known-biller list whose
    ref is also a prior payee in `ctx`."""
    billers = {b.strip().lower() for b in ctx.known_billers}
    return {
        name.strip().lower(): ref
        for name, ref in pairs
        if name.strip().lower() in billers and ref in ctx.prior_payees
    }


def mint_ref(name: str) -> str:
    """Fresh ref for an unknown payee name: ext_new_ + sha256(name.lower())[:8]."""
    digest = hashlib.sha256(name.strip().lower().encode("utf-8")).hexdigest()
    return NEW_REF_PREFIX + digest[:8]


def resolve_ref(name: str, directory: dict[str, str]) -> str:
    return directory.get(name.strip().lower()) or mint_ref(name)


ROOM_PREFIX = "room_"
ATTACK_PREFIX = "attack:"
Origin = Literal["room", "attack", "ops"]


def origin_of(conversation_id: str) -> Origin:
    """Where a payment came from, for counts and the balance display: `room` (Margaret in a
    room), `attack` (the attack panel; never a legitimate completion), else `ops`."""
    if conversation_id.startswith(ROOM_PREFIX):
        return "room"
    if conversation_id.startswith(ATTACK_PREFIX):
        return "attack"
    return "ops"


class DemoScript(BaseModel):
    model_config = ConfigDict(frozen=True)
    player_id: str = "scripted-demo"
    turns: tuple[str, ...]
    followup: str | None = None


def load_demo_script(path: Path | None = None) -> DemoScript:
    """`fixtures/demo_script.json`: the proven IRS/warmth script shared with scripts/demo.py."""
    p = path or repo_root() / "fixtures" / "demo_script.json"
    raw = json.loads(p.read_text("utf-8"))
    return DemoScript(
        player_id=str(raw.get("player_id") or "scripted-demo"),
        turns=tuple(str(t) for t in raw["turns"]),
        followup=str(raw["followup"]) if raw.get("followup") else None,
    )


def load_shared_evidence(path: Path | None = None) -> tuple[EvidenceItem, ...]:
    """`fixtures/evidence.json` as evidence items with speaker "reference": the extractor
    renders them as context and never cites them as counterparty speech."""
    p = path or repo_root() / "fixtures" / "evidence.json"
    raw = json.loads(p.read_text("utf-8"))
    out: list[EvidenceItem] = []
    for item in raw:
        out.append(
            EvidenceItem(id=str(item["id"]), speaker=REFERENCE_SPEAKER, text=str(item["text"]))
        )
    return tuple(out)


class Room(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    id: str
    history: list[EvidenceItem] = Field(default_factory=list)
    persuasion: float = Field(default=START_PERSUASION, ge=0.0, le=1.0)
    payment_id: str | None = None
    balance_cents: int = START_BALANCE_CENTS  # display only; decremented once per SUBMITTED
    settled_payment_ids: list[str] = Field(default_factory=list)
    turn_count: int = 0
    ctx: AccountContext
    payee_directory: dict[str, str] = Field(default_factory=dict)
    scam_cues: set[str] = Field(default_factory=set)


class TurnResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    room_id: str
    turn_id: str
    player_id: str
    evidence_id: str
    margaret_text: str
    margaret_audio_url: str | None
    persuasion: float
    persuaded: bool
    payment_id: str | None
    payment_created: bool
    stage: int
    outcome: dict[str, Any] | None
    public_outcome: dict[str, Any] | None

    def as_api(self) -> dict[str, Any]:
        """The docs/api.md `POST /rooms/{room}/turns` response (bridge and board view)."""
        return {
            "margaret_text": self.margaret_text,
            "margaret_audio_url": self.margaret_audio_url,
            "persuaded": self.persuaded,
            "payment_id": self.payment_id,
            "stage": self.stage,
            "outcome": self.outcome,
        }


def stage_for(persuaded: bool, payment: Payment | None) -> int:
    """How far the attacker got. 10 nothing, 40 persuaded but no payment, 60 payment created
    (PENDING_REVIEW, DENIED, CANCELLED), 70 HELD, 90 ELIGIBLE_TO_SUBMIT, 100 SUBMITTED."""
    if payment is None:
        return 40 if persuaded else 10
    if payment.state is State.HELD:
        return 70
    if payment.state is State.ELIGIBLE_TO_SUBMIT:
        return 90
    if payment.state is State.SUBMITTED:
        return 100
    return 60


def draft_to_payment_in(d: DraftPayment, room: Room) -> PaymentIn:
    """A draft is a proposal. The ref comes from the room's payee directory (exact name match)
    or is freshly minted; `is_new` comes from the room context, never from the model."""
    ref = resolve_ref(d.payee_name, room.payee_directory)
    return PaymentIn(
        account_id=MARGARET_ACCOUNT_ID,
        amount_cents=d.amount_cents,
        currency="USD",
        beneficiary=Beneficiary(
            name=d.payee_name.strip()[:80] or "the caller",
            account_ref=ref,
            is_new=ref not in room.ctx.prior_payees,
        ),
        rail=d.rail,
        conversation_id=f"{ROOM_PREFIX}{room.id}",
    )


def full_outcome(decision: Decision | None, refusal: Refusal | None) -> dict[str, Any] | None:
    """Bank-side outcome: decision, rule ids, refusal text. For the bridge and the board."""
    if decision is None and refusal is None:
        return None
    if refusal is not None:
        return {
            "decision": "REFUSED",
            "rule_ids": list(decision.rule_ids) if decision else [],
            "refusal": refusal.text,
        }
    assert decision is not None
    return {
        "decision": decision.outcome.value,
        "rule_ids": list(decision.rule_ids),
        "refusal": None,
    }


def public_outcome(decision: Decision | None, refusal: Refusal | None) -> dict[str, Any] | None:
    """Attacker-facing outcome: decision and refusal only. Never rule ids."""
    full = full_outcome(decision, refusal)
    if full is None:
        return None
    return {"decision": full["decision"], "refusal": full["refusal"]}


class SessionStore:
    """All rooms in this process. One lock; turns are short except for the model calls."""

    def __init__(
        self,
        kernel: Kernel,
        margaret: Margaret,
        *,
        default_ctx: AccountContext,
        evidence: Sequence[EvidenceItem] = (),
        tts: TTS | None = None,
        voice_id: str = DEFAULT_VOICE_ID,
        tts_budget_s: float = TTS_BUDGET_S,
    ) -> None:
        self.kernel = kernel
        self.margaret = margaret
        self.default_ctx = default_ctx
        self.evidence = tuple(evidence)
        self.tts = tts
        self.voice_id = voice_id
        self.tts_budget_s = tts_budget_s
        self._rooms: dict[str, Room] = {}
        self._lock = threading.RLock()
        self._tts_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="tts")

    @staticmethod
    def normalize(room_id: str) -> str:
        """Same rule as the room store (3 to 16 of [A-Z0-9-]); raises RoomError otherwise."""
        return RoomStore.normalize_code(room_id)

    def _new_room(self, rid: str) -> Room:
        return Room(id=rid, ctx=self.default_ctx, payee_directory=payee_directory(self.default_ctx))

    def room(self, room_id: str) -> Room:
        rid = self.normalize(room_id)
        with self._lock:
            r = self._rooms.get(rid)
            if r is None:
                r = self._new_room(rid)
                self._rooms[rid] = r
            return r

    def close(self) -> None:
        """Stop the TTS worker threads. Idempotent."""
        self._tts_pool.shutdown(wait=False, cancel_futures=True)

    def rooms(self) -> list[Room]:
        with self._lock:
            return list(self._rooms.values())

    def reset(self, room_id: str) -> Room:
        rid = self.normalize(room_id)
        with self._lock:
            r = self._new_room(rid)
            self._rooms[rid] = r
        log.info("room.reset", extra={"room_id": rid})
        return r

    def open_payment(self, room_id: str) -> Payment | None:
        """The room's payment if it is still pre-settlement, else None."""
        p = self.current_payment(self.room(room_id))
        return p if p is not None and p.state in OPEN_STATES else None

    def current_payment(self, room: Room) -> Payment | None:
        if room.payment_id is None:
            return None
        try:
            return self.kernel.get(room.payment_id).payment
        except KeyError:
            return None

    def take_turn(
        self,
        room_id: str,
        turn_id: str,
        player_id: str,
        text: str,
        deadline: float | None = None,
    ) -> TurnResult:
        """`deadline` is a `time.monotonic()` value (default: the hub's `TURN_DEADLINE`). Past
        it, no payment is created; one created while it passed is cancelled at once."""
        if deadline is None:
            deadline = TURN_DEADLINE.get()
        room = self.room(room_id)
        with self._lock:
            history = list(room.history)
            persuasion = room.persuasion
        # Model calls outside the room lock: output is data only.
        turn = self.margaret.reply(history, text, persuasion)
        reply = turn.reply.replace("—", ",")

        # Track distinct cues for the display score only. Cues must not change
        # progression or payment eligibility; those remain model/policy-driven.
        hits = scan(text)
        with self._lock:
            room.scam_cues.update(hit.kind for hit in hits)
            cue_count = len(room.scam_cues)

        effective_persuasion = turn.persuasion
        persuaded = effective_persuasion > DRAFT_THRESHOLD

        log.info(
            "room.progression",
            extra={
                "room_id": room.id,
                "model_persuasion": round(turn.persuasion, 3),
                "effective_persuasion": round(effective_persuasion, 3),
                "cue_count": cue_count,
                "cue_categories": sorted(room.scam_cues),
                "persuaded": persuaded,
            },
)

        with self._lock:
            n = len(room.history) + 1
            caller = EvidenceItem(id=f"EV-{n:04d}", speaker="caller", text=text)
            margaret = EvidenceItem(id=f"EV-{n + 1:04d}", speaker="margaret", text=reply)
            room.history.extend([caller, margaret])
            room.persuasion = effective_persuasion
            room.turn_count += 1
            transcript = tuple(room.history)
            payment = self.current_payment(room)
            open_payment = payment is not None and payment.state in OPEN_STATES

        decision: Decision | None = None
        refusal: Refusal | None = None
        failure: str | None = None
        created = False
        if turn.draft_payment is not None and not open_payment and _expired(deadline):
            log.warning("room.turn.late", extra={"room_id": room.id, "turn_id": turn_id})
            failure = TIMED_OUT_TEXT
        elif turn.draft_payment is not None and not open_payment:
            try:
                p_in = draft_to_payment_in(turn.draft_payment, room)
                payment, decision = self.kernel.create_payment(
                    p_in, room.ctx, (*transcript, *self.evidence)
                )
                if _expired(deadline):
                    # The hub already failed closed on this turn: the payment must not sit in
                    # the ops queue (ELIGIBLE on a known biller) while the board says stage 10.
                    self._cancel_late(payment, room.id, turn_id)
                    payment, decision, failure = None, None, TIMED_OUT_TEXT
                else:
                    created = True
                    with self._lock:
                        room.payment_id = payment.id
            except Refusal as r:
                refusal = r
            except Exception as e:  # noqa: BLE001  fail closed: the turn still answers
                log.warning(
                    "room.payment.failed",
                    extra={"room_id": room.id, "error": f"{type(e).__name__}: {e}"},
                )
                failure = FAIL_CLOSED_TEXT
        elif payment is not None:
            decision = self.kernel.get(payment.id).decision

        stage = stage_for(persuaded, payment)
        if payment is not None and payment.state is State.SUBMITTED:
            with self._lock:
                if payment.id not in room.settled_payment_ids:
                    room.settled_payment_ids.append(payment.id)
                    room.balance_cents = max(0, room.balance_cents - payment.amount_cents)
        audio = self._synthesize(reply)
        result = TurnResult(
            room_id=room.id,
            turn_id=turn_id,
            player_id=player_id,
            evidence_id=caller.id,
            margaret_text=reply,
            margaret_audio_url=audio,
            persuasion=effective_persuasion,
            persuaded=persuaded,
            payment_id=payment.id if payment is not None else None,
            payment_created=created,
            stage=stage,
            outcome=_failed_outcome(failure) or full_outcome(decision, refusal),
            public_outcome=_failed_public(failure) or public_outcome(decision, refusal),
        )
        log.info(
            "room.turn",
            extra={
                "room_id": room.id,
                "turn_id": turn_id,
                "stage": stage,
                "persuasion": round(turn.persuasion, 2),
                "payment_created": created,
                "audio": audio is not None,
            },
        )
        return result

    def _cancel_late(self, payment: Payment, room_id: str, turn_id: str) -> None:
        self.kernel.audit.append(
            TIMEOUT_ACTOR,
            "ROOM_TURN_TIMEOUT",
            {"payment_id": payment.id, "room_id": room_id, "turn_id": turn_id},
        )
        try:
            self.kernel.cancel(
                payment.id, TIMEOUT_ACTOR, Capability.BANK_REVIEW, note="turn timed out"
            )
        except Refusal as r:  # DENIED is already terminal; nothing certifiable remains
            log.info("room.turn.late.refused", extra={"payment_id": payment.id, "text": r.text})
        log.warning(
            "room.turn.late.cancelled", extra={"payment_id": payment.id, "turn_id": turn_id}
        )

    def _synthesize(self, text: str) -> str | None:
        if self.tts is None or not text:
            return None
        fut = self._tts_pool.submit(self.tts.synthesize, text, self.voice_id)
        try:
            path = fut.result(timeout=self.tts_budget_s)
        except TimeoutError:
            log.warning("room.tts.timeout", extra={"budget_s": self.tts_budget_s})
            return None
        except Exception as e:  # noqa: BLE001  audio is optional
            log.warning("room.tts.failed", extra={"error": type(e).__name__})
            return None
        return audio_url(path) if path is not None else None


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() > deadline


def _failed_outcome(failure: str | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    return {"decision": "HOLD", "rule_ids": [], "refusal": failure}


def _failed_public(failure: str | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    return {"decision": "HOLD", "refusal": failure}
