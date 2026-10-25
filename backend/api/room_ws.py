"""Room routes for memory mode (SpacetimeDB fallback) and the room WebSocket.

Routes
    POST /rooms/{room}/join      {handle} -> {player_id, player_token, room_id}
    POST /rooms/{room}/submit    {text, audio_url?} + header X-Player-Token -> {turn_id}
    GET  /rooms/{room}/snapshot?role=attacker|board|ops -> RoomSnapshot (camelCase);
         attacker view bound to X-Player-Token, board/ops to X-Ops-Token
    WS   /ws?room=&role=&player_token=|token=  pushes {"type": "room", "snapshot": ...} on change,
                                      relays kernel events passed to `RoomHub.broadcast_event`,
                                      accepts {"type": "submit_turn", "text", "player_token"}.

In memory mode the hub is the bridge: a queued turn is handed to a `TurnTaker`
(the lead binds the real SessionStore; `StubTurnTaker` answers with a fixed line
and stage 10 until then). Any TurnTaker error or timeout is a stage-10 HOLD with
"kernel unavailable, fail closed". Nothing here can touch a payment.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Protocol

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field

from api.ratelimit import ADDRESS_BURST, ADDRESS_WINDOW_S, JOIN_BURST, JOIN_WINDOW_S, WindowLimiter
from kernel.clock import Clock, SystemClock
from kernel.room_memory import RoomError, RoomSnapshot, RoomStore, SnapshotRole, TurnRow
from kernel.rooms import TURN_DEADLINE

log = logging.getLogger("second_key.room")

# Real-mode budget: Margaret 12 s + extractor 8 s + TTS 4 s + 1 s slack.
MARGARET_BUDGET_S = 12.0
EXTRACTOR_BUDGET_S = 8.0
TTS_BUDGET_S = 4.0
TURN_TIMEOUT_S = MARGARET_BUDGET_S + EXTRACTOR_BUDGET_S + TTS_BUDGET_S + 1.0
ATTACKER_EVENT_TYPES = frozenset({"room", "margaret"})
FAIL_CLOSED_REFUSAL = "kernel unavailable, fail closed"
STAGES = {0, 10, 40, 60, 70, 90, 100}
DECISIONS = {"ALLOW", "HOLD", "DENY", "REFUSED", "NONE"}


class TurnTaker(Protocol):
    """One attacker turn in, Margaret's answer and the policy outcome out.

    Return shape is the docs/api.md turn response:
    {margaret_text, margaret_audio_url, persuaded, payment_id?, stage,
     outcome?: {decision, rule_ids, refusal?}}
    Sync by design (the SessionStore is sync); the hub runs it in a thread.
    """

    def take_turn(
        self, room_id: str, turn_id: str, player_id: str, text: str
    ) -> dict[str, Any]: ...


class AuditSource(Protocol):
    """Optional: recent kernel audit events to mirror onto the board."""

    def recent(self, limit: int) -> list[Mapping[str, Any]]: ...


class StubTurnTaker:
    """Fixed Margaret line, stage 10, no payment. Used until the SessionStore lands."""

    line = "Oh, hello dear. I would rather talk to my bank before I send anything."

    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> dict[str, Any]:
        return {
            "margaret_text": self.line,
            "margaret_audio_url": None,
            "persuaded": False,
            "payment_id": None,
            "stage": 10,
            "outcome": None,
        }


def fail_closed_response() -> dict[str, Any]:
    return {
        "margaret_text": "",
        "margaret_audio_url": None,
        "persuaded": False,
        "payment_id": None,
        "stage": 10,
        "outcome": {"decision": "HOLD", "rule_ids": [], "refusal": FAIL_CLOSED_REFUSAL},
    }


class _Normalized(BaseModel):
    margaret_text: str
    margaret_audio_url: str
    persuaded: bool
    payment_id: str
    stage: int
    decision: str
    rule_ids: list[str]
    refusal: str


def normalize_turn_response(raw: Mapping[str, Any]) -> _Normalized:
    """Strict parse of a TurnTaker result. Anything malformed raises -> fail closed."""
    stage = int(raw["stage"])
    if stage not in STAGES:
        raise ValueError(f"bad stage {stage}")
    text = raw.get("margaret_text")
    if not isinstance(text, str):
        raise ValueError("margaret_text missing")
    outcome = raw.get("outcome") or {}
    decision = str(outcome.get("decision", "NONE")) if outcome else "NONE"
    if decision not in DECISIONS:
        raise ValueError(f"bad decision {decision}")
    rule_ids = [str(r) for r in (outcome.get("rule_ids") or [])] if outcome else []
    refusal = outcome.get("refusal") if outcome else None
    audio = raw.get("margaret_audio_url")
    payment_id = raw.get("payment_id")
    return _Normalized(
        margaret_text=text,
        margaret_audio_url=audio if isinstance(audio, str) else "",
        persuaded=bool(raw.get("persuaded", False)),
        payment_id=payment_id if isinstance(payment_id, str) else "",
        stage=stage,
        decision=decision,
        rule_ids=rule_ids,
        refusal=refusal if isinstance(refusal, str) else "",
    )


class _Subscriber:
    def __init__(self, ws: WebSocket, room_id: str, role: SnapshotRole, player_id: str | None):
        self.ws = ws
        self.room_id = room_id
        self.role = role
        self.player_id = player_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()


class RoomHub:
    """Owns the store, the player tokens, the WS subscribers and the in-process turn loop."""

    def __init__(
        self,
        store: RoomStore | None = None,
        taker: TurnTaker | None = None,
        clock: Clock | None = None,
        audit: AuditSource | None = None,
        turn_timeout_s: float = TURN_TIMEOUT_S,
    ) -> None:
        self.store = store or RoomStore()
        self.taker: TurnTaker = taker or StubTurnTaker()
        self.clock: Clock = clock or SystemClock()
        self.audit = audit
        self.turn_timeout_s = turn_timeout_s
        self.tokens: dict[str, str] = {}  # player_token -> player_id
        # Per-address budgets: the player token is free to mint, the address is not.
        self.address_limiter = WindowLimiter(ADDRESS_BURST, ADDRESS_WINDOW_S)
        self.join_limiter = WindowLimiter(JOIN_BURST, JOIN_WINDOW_S)
        self._subs: set[_Subscriber] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._processed: set[int] = set()
        self._last_audit_seq = 0

    # -- players -------------------------------------------------------------

    def ensure_room(self, code: str) -> str:
        c = RoomStore.normalize_code(code)
        if c not in self.store.rooms:
            self.store.create_room(c, self.clock.now())
            self.store.set_room_status(c, "live")
        return c

    def join(self, code: str, handle: str, address: str | None = None) -> tuple[str, str]:
        if address is not None and not self.join_limiter.allow(f"join:{address}"):
            raise RoomError("RATE_LIMIT", f"rate limit: {JOIN_BURST} joins per minute")
        room_id = self.ensure_room(code)
        player = self.store.join(room_id, handle, self.clock.now())
        token = secrets.token_urlsafe(24)
        self.tokens[token] = player.identity
        self.changed()
        return player.identity, token

    def player_for_token(self, token: str | None) -> str:
        pid = self.tokens.get(token or "")
        if pid is None:
            raise RoomError("NOT_ATTACKER", "unknown player token")
        return pid

    def player_or_none(self, token: str | None) -> str | None:
        """Attacker views are bound to the token; a bare player id is never trusted."""
        return self.tokens.get(token or "") if token else None

    async def submit_player_turn(
        self,
        room_id: str,
        player_id: str,
        text: str,
        audio_url: str = "",
        address: str | None = None,
    ) -> TurnRow:
        """Validate and queue a turn, then process it in the background (the memory bridge)."""
        if address is not None and not self.address_limiter.allow(f"turn:{address}"):
            raise RoomError(
                "RATE_LIMIT", f"rate limit: {ADDRESS_BURST} turns per {ADDRESS_WINDOW_S:g}s"
            )
        turn = self.store.submit_turn(room_id, player_id, text, self.clock.now(), audio_url)
        self.changed()
        task = asyncio.create_task(self._process(turn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return turn

    # -- the in-process bridge loop ----------------------------------------

    async def _process(self, turn: TurnRow) -> None:
        if turn.id in self._processed:
            return
        self._processed.add(turn.id)
        try:
            self.store.claim_turn(turn.id)
        except RoomError as e:
            log.info("room.turn.skip", extra={"turn": turn.id, "reason": e.message})
            return
        self.changed()
        failed = False
        # The deadline rides in the context that to_thread copies: once we give up below, the
        # abandoned thread must not create (or keep) a payment for this turn.
        reset_token = TURN_DEADLINE.set(time.monotonic() + self.turn_timeout_s)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(
                    self.taker.take_turn, turn.room_id, str(turn.id), turn.player, turn.text
                ),
                timeout=self.turn_timeout_s,
            )
            result = normalize_turn_response(raw)
            log.info("room.turn.ok", extra={"turn": turn.id, "stage": result.stage})
        except Exception as e:  # noqa: BLE001 - any failure fails closed
            failed = True
            result = normalize_turn_response(fail_closed_response())
            log.warning(
                "room.turn.failclosed",
                extra={"turn": turn.id, "error": str(e)},
                exc_info=True,
            )

        finally:
            TURN_DEADLINE.reset(reset_token)
        now = self.clock.now()
        if not failed:
            self.store.record_reply(
                turn.id, result.margaret_text, result.margaret_audio_url, result.persuaded, now
            )
        self.store.record_outcome(
            turn.id,
            result.stage,
            result.payment_id,
            result.decision,
            result.rule_ids,
            result.refusal,
            now,
        )
        if not failed:
            self._mirror_audit(turn.room_id)
        self.changed()
        self.broadcast_event(
            {
                "type": "margaret",
                "room_id": turn.room_id,
                "turn_id": turn.id,
                "text": result.margaret_text,
                "audio_url": result.margaret_audio_url or None,
                "persuaded": result.persuaded,
            }
        )

    def _mirror_audit(self, room_id: str) -> None:
        if self.audit is None:
            return
        try:
            events = self.audit.recent(50)
        except Exception as e:  # noqa: BLE001 - mirror is best effort
            log.warning("room.audit.skip", extra={"error": str(e)})
            return
        for ev in sorted(events, key=lambda e: int(e["seq"])):
            seq = int(ev["seq"])
            if seq <= self._last_audit_seq:
                continue
            self.store.mirror_audit(
                room_id,
                seq,
                str(ev.get("kind", "")),
                str(ev.get("hash", "")),
                str(ev.get("prev_hash", "")),
                str(ev.get("ts", "")),
            )
            self._last_audit_seq = seq

    async def drain(self) -> None:
        """Wait for in-flight turns (tests)."""
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # -- subscribers ---------------------------------------------------------

    def snapshot(self, room_id: str, role: SnapshotRole, player_id: str | None) -> RoomSnapshot:
        return self.store.snapshot(room_id, role, player_id)

    def _room_message(self, sub: _Subscriber) -> dict[str, Any]:
        snap = self.snapshot(sub.room_id, sub.role, sub.player_id)
        return {"type": "room", "snapshot": snap.model_dump(by_alias=True, mode="json")}

    def changed(self) -> None:
        """Push a fresh snapshot to every subscriber. Call after any direct store mutation."""
        for sub in list(self._subs):
            sub.queue.put_nowait(self._room_message(sub))

    def broadcast_event(self, event: Mapping[str, Any]) -> None:
        """Relay a kernel event ({type: payment|margaret|attack, ...}) to the sockets allowed
        to see it. Attacker sockets get only `room` and `margaret` events, and `margaret` only
        for their own room; payment and attack events (rule ids, fingerprints, refusals) go to
        board and ops sockets only."""
        room_id = event.get("room_id")
        kind = str(event.get("type", ""))
        for sub in list(self._subs):
            if sub.role == "attacker":
                if kind not in ATTACKER_EVENT_TYPES or room_id != sub.room_id:
                    continue
            elif room_id is not None and sub.room_id != room_id:
                continue
            sub.queue.put_nowait(dict(event))

    def _add(self, sub: _Subscriber) -> None:
        self._subs.add(sub)
        sub.queue.put_nowait(self._room_message(sub))

    def _remove(self, sub: _Subscriber) -> None:
        self._subs.discard(sub)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class JoinBody(BaseModel):
    handle: str = Field(min_length=1, max_length=64)


class SubmitBody(BaseModel):
    text: str = Field(max_length=4000)
    audio_url: str = ""


def _http(e: RoomError) -> HTTPException:
    status = {
        "TOO_LONG": 400,
        "RATE_LIMIT": 429,
        "CLOSED": 409,
        "NOT_FOUND": 404,
        "NOT_ATTACKER": 401,
        "BAD_HANDLE": 400,
        "EXISTS": 409,
        "BAD_INPUT": 400,
        "EMPTY": 400,
    }[e.code]
    return HTTPException(status_code=status, detail={"code": e.code, "message": e.message})


Authorizer = Callable[[str, str | None], bool]


def allow_all(role: str, token: str | None) -> bool:
    return True


def _address(request: Request) -> str | None:
    """The peer address, for per-address budgets. (Behind the Next.js rewrite every browser
    shares the proxy's address; the budgets are sized as bursts for that reason.)"""
    return request.client.host if request.client else None


def make_router(hub: RoomHub, authorize: Authorizer = allow_all) -> APIRouter:
    """`authorize(role, token)` gates the board and ops views: `X-Ops-Token` header for
    `/snapshot`, `?token=` query for `/ws` (browsers cannot set headers on a WebSocket).
    The attacker role must never need a token."""
    router = APIRouter(tags=["room"])

    def _check(role: str, header: str | None, query: str | None) -> bool:
        return role == "attacker" or authorize(role, header or query)

    @router.post("/rooms/{room}/join")
    async def join(room: str, body: JoinBody, request: Request) -> dict[str, str]:
        # async so hub.changed() (asyncio queues) runs on the loop, not in a worker thread.
        try:
            player_id, token = hub.join(room, body.handle, _address(request))
        except RoomError as e:
            raise _http(e) from e
        return {
            "player_id": player_id,
            "player_token": token,
            "room_id": RoomStore.normalize_code(room),
        }

    @router.post("/rooms/{room}/submit")
    async def submit(
        room: str,
        body: SubmitBody,
        request: Request,
        x_player_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, int]:
        try:
            player_id = hub.player_for_token(x_player_token)
            turn = await hub.submit_player_turn(
                RoomStore.normalize_code(room),
                player_id,
                body.text,
                body.audio_url,
                address=_address(request),
            )
        except RoomError as e:
            raise _http(e) from e
        return {"turn_id": turn.id}

    @router.get("/rooms/{room}/snapshot")
    def snapshot(
        room: str,
        role: Annotated[SnapshotRole, Query()] = "board",
        x_ops_token: Annotated[str | None, Header()] = None,
        x_player_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        # Header only: a token in a URL lands in proxy and browser logs. `/ws` keeps `?token=`
        # because browsers cannot set headers on a WebSocket. The attacker's own view is bound
        # to X-Player-Token; a `player_id` query is ignored.
        player_id = hub.player_or_none(x_player_token) if role == "attacker" else None
        if not _check(role, x_ops_token, None):
            raise HTTPException(
                status_code=401, detail={"code": "NOT_OPERATOR", "message": "ops token required"}
            )
        try:
            room_id = RoomStore.normalize_code(room)
        except RoomError as e:
            raise _http(e) from e
        snap = hub.snapshot(room_id, role, player_id)
        return snap.model_dump(by_alias=True, mode="json")

    @router.websocket("/ws")
    async def ws(
        websocket: WebSocket,
        room: Annotated[str, Query()] = "DEMO",
        role: Annotated[SnapshotRole, Query()] = "board",
        token: Annotated[str | None, Query()] = None,
        player_token: Annotated[str | None, Query()] = None,
    ) -> None:
        await websocket.accept()
        player_id = hub.player_or_none(player_token) if role == "attacker" else None
        if not _check(role, websocket.headers.get("x-ops-token"), token):
            await websocket.send_json(
                {"type": "error", "code": "NOT_OPERATOR", "message": "ops token required"}
            )
            await websocket.close(code=4401)
            return
        try:
            room_id = RoomStore.normalize_code(room)
        except RoomError as e:
            await websocket.send_json({"type": "error", "code": e.code, "message": e.message})
            await websocket.close()
            return
        sub = _Subscriber(websocket, room_id, role, player_id)
        hub._add(sub)

        async def sender() -> None:
            while True:
                msg = await sub.queue.get()
                await websocket.send_json(msg)

        send_task = asyncio.create_task(sender())
        try:
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    continue
                kind = data.get("type")
                if kind == "submit_turn":
                    try:
                        pid = hub.player_for_token(data.get("player_token"))
                        turn = await hub.submit_player_turn(
                            room_id,
                            pid,
                            str(data.get("text", "")),
                            str(data.get("audio_url", "") or ""),
                            address=websocket.client.host if websocket.client else None,
                        )
                        await websocket.send_json({"type": "turn_accepted", "turn_id": turn.id})
                    except RoomError as e:
                        await websocket.send_json(
                            {"type": "error", "code": e.code, "message": e.message}
                        )
                elif kind == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001 - never let one socket take the hub down
            log.info("room.ws.closed", extra={"error": str(e)})
        finally:
            send_task.cancel()
            hub._remove(sub)

    return router
