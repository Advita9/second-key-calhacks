"""Rooms: one attacker turn in, Margaret's answer and the outcome out; reset.

`POST /rooms/{room}/turns` has two callers with different trust:
- the bridge sends JSON `{turn_id, player_id, text, audio_url?}` and gets the full outcome
  (rule ids). When BRIDGE_TOKEN (or OPS_TOKEN) is set it must send `X-Bridge-Token` (or
  `X-Ops-Token`).
- a push-to-talk client sends a form (`text` and/or `audio`; audio goes through STT) and gets
  the public outcome: decision and refusal, never rule ids.
The memory-mode room routes (`/join`, `/submit`, `/snapshot`, `/ws`) come from
`api.room_ws.make_router` and are mounted by `api.main`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from api import deps
from api.hub import EventBus
from api.schemas import MAX_TURN_CHARS, TurnIn
from api.voice_routes import MAX_AUDIO_BYTES, get_stt
from kernel.models import Capability
from kernel.room_memory import RoomError, RoomStore
from kernel.rooms import SessionStore, TurnResult

log = logging.getLogger("second_key.api.rooms")

router = APIRouter(tags=["rooms"])
Bus = Annotated[EventBus, Depends(deps.get_bus)]
RESET_ACTOR = "ops_reset"


def _room_code(room: str) -> str:
    try:
        return RoomStore.normalize_code(room)
    except RoomError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message}) from e


async def _parse_turn(request: Request) -> tuple[TurnIn, bool]:
    """(turn, is_bridge). Form bodies are the player path; JSON is the bridge path."""
    ctype = (request.headers.get("content-type") or "").lower()
    if ctype.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        form = await request.form()
        text = str(form.get("text") or "")
        audio = form.get("audio")
        if audio is not None and not isinstance(audio, str):
            data = await audio.read()
            if len(data) > MAX_AUDIO_BYTES:
                raise HTTPException(status_code=413, detail="audio clip too large")
            if data:
                mime = audio.content_type or "application/octet-stream"
                t = await asyncio.to_thread(get_stt().transcribe, data, mime, hint=text or None)
                text = t.text
        if len(text) > MAX_TURN_CHARS:
            raise HTTPException(status_code=400, detail=f"text over {MAX_TURN_CHARS} chars")
        turn = TurnIn(
            turn_id=str(form.get("turn_id") or "ptt"),
            player_id=str(form.get("player_id") or "player"),
            text=text,
            audio_url=None,
        )
        return turn, False
    try:
        body = await request.json()
    except ValueError as e:
        raise HTTPException(status_code=400, detail="body must be JSON or a form") from e
    try:
        return TurnIn.model_validate(body), True
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False)) from e


def run_turn(sessions: SessionStore, bus: EventBus, room: str, turn: TurnIn) -> TurnResult:
    result = sessions.take_turn(room, str(turn.turn_id), turn.player_id, turn.text)
    if result.payment_id is not None:
        try:
            bus.payment(sessions.kernel.get(result.payment_id))
        except KeyError:
            pass
    return result


@router.post("/rooms/{room}/turns")
async def turns(
    room: str,
    request: Request,
    bus: Bus,
    x_bridge_token: Annotated[str | None, Header()] = None,
    x_ops_token: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    room_id = _room_code(room)
    turn, is_bridge = await _parse_turn(request)
    if is_bridge:
        deps.check_bridge(x_bridge_token or x_ops_token)
    if not turn.text.strip():
        raise HTTPException(status_code=400, detail="empty turn")
    sessions = deps.get_sessions()
    result = await asyncio.to_thread(run_turn, sessions, bus, room_id, turn)
    bus.margaret(
        result.room_id,
        result.margaret_text,
        result.margaret_audio_url,
        result.persuaded,
        turn_id=str(turn.turn_id),
        stage=result.stage,
    )
    out = result.as_api()
    if not is_bridge:
        out["outcome"] = result.public_outcome
    return out


@router.post("/rooms/{room}/reset", dependencies=[Depends(deps.ops_guard)])
async def reset(room: str, bus: Bus) -> dict[str, Any]:
    """Fresh Margaret, balance restored, the room's open payment cancelled (voiding every
    attestation and certificate on it). Async so `hub.changed()` runs on the loop."""
    room_id = _room_code(room)
    sessions = deps.get_sessions()
    kernel = sessions.kernel
    cancelled: str | None = None
    open_payment = await asyncio.to_thread(sessions.open_payment, room_id)
    if open_payment is not None:
        await asyncio.to_thread(
            kernel.cancel, open_payment.id, RESET_ACTOR, Capability.BANK_REVIEW, "room reset"
        )
        cancelled = open_payment.id
        bus.payment(kernel.get(open_payment.id))
    fresh = sessions.reset(room_id)
    hub = bus.hub
    try:
        hub.store.reset_room(fresh.id)
        hub.changed()
    except RoomError:
        pass  # no memory-mode room with that code; nothing to clear
    bus.publish({"type": "room_reset", "room_id": fresh.id})
    log.info("room.reset", extra={"room_id": fresh.id, "cancelled_payment": cancelled})
    return {
        "ok": True,
        "room_id": fresh.id,
        "persuasion": fresh.persuasion,
        "balance_cents": fresh.balance_cents,
        "cancelled_payment_id": cancelled,
    }
