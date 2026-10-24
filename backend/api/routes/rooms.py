"""Rooms: one attacker turn in, Margaret's answer and the outcome out; reset.

`POST /rooms/{room}/turns` accepts JSON from the bridge (`{turn_id, player_id, text,
audio_url?}`) and multipart from a push-to-talk client (`text` and/or `audio`; audio goes
through STT first). The memory-mode room routes (`/join`, `/submit`, `/snapshot`, `/ws`)
come from `api.room_ws.make_router` and are mounted by `api.main`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api import deps
from api.hub import EventBus
from api.schemas import TurnIn
from api.voice_routes import MAX_AUDIO_BYTES, get_stt
from kernel.room_memory import RoomError
from kernel.rooms import SessionStore, TurnResult

log = logging.getLogger("second_key.api.rooms")

router = APIRouter(tags=["rooms"])
Bus = Annotated[EventBus, Depends(deps.get_bus)]


async def _parse_turn(request: Request) -> TurnIn:
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
        return TurnIn(
            turn_id=str(form.get("turn_id") or "ptt"),
            player_id=str(form.get("player_id") or "player"),
            text=text,
            audio_url=None,
        )
    try:
        body = await request.json()
    except ValueError as e:
        raise HTTPException(status_code=400, detail="body must be JSON or multipart") from e
    return TurnIn.model_validate(body)


def run_turn(sessions: SessionStore, bus: EventBus, room: str, turn: TurnIn) -> TurnResult:
    result = sessions.take_turn(room, str(turn.turn_id), turn.player_id, turn.text)
    if result.payment_id is not None:
        try:
            bus.payment(sessions.kernel.get(result.payment_id))
        except KeyError:
            pass
    return result


@router.post("/rooms/{room}/turns")
async def turns(room: str, request: Request, bus: Bus) -> dict[str, Any]:
    turn = await _parse_turn(request)
    if not turn.text.strip():
        raise HTTPException(status_code=400, detail="empty turn")
    sessions = deps.get_sessions()
    result = await asyncio.to_thread(run_turn, sessions, bus, room, turn)
    bus.margaret(
        result.room_id,
        result.margaret_text,
        result.margaret_audio_url,
        result.persuaded,
        turn_id=str(turn.turn_id),
        stage=result.stage,
    )
    return result.as_api()


@router.post("/rooms/{room}/reset", dependencies=[Depends(deps.ops_guard)])
def reset(room: str, request: Request, bus: Bus) -> dict[str, Any]:
    sessions = deps.get_sessions()
    fresh = sessions.reset(room)
    hub = bus.hub
    try:
        hub.store.reset_room(fresh.id)
        hub.changed()
    except RoomError:
        pass  # no memory-mode room with that code; nothing to clear
    bus.publish({"type": "room_reset", "room_id": fresh.id})
    log.info("room.reset", extra={"room_id": fresh.id})
    return {
        "ok": True,
        "room_id": fresh.id,
        "persuasion": fresh.persuasion,
        "balance_cents": fresh.balance_cents,
    }
