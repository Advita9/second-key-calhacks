"""FastAPI entrypoint: `uv run uvicorn api.main:app --port 8000`.

Routes per docs/api.md: payments, rooms, attack panel, audit, eval, health, the voice routes
and the memory-mode room router with the `/ws` socket. `Refusal` becomes a 409
`{refused, invariant, text}`; the operator credential (amendment 6) a 401.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import deps
from api.hub import EventBus
from api.room_ws import RoomHub, make_router
from api.routes import attack, audit, evalres, payments, rooms
from api.voice_routes import router as voice_router
from api.voice_routes import set_stt
from kernel.models import Refusal
from kernel.rail import RailError
from kernel.state import IllegalTransition
from kernel.voice.factory import make_stt

log = logging.getLogger("second_key.api")


class SessionTurnTaker:
    """`TurnTaker` for the memory-mode room hub: the real SessionStore, resolved lazily so the
    app builds before the env is read."""

    def __init__(self, bus_ref: list[EventBus]) -> None:
        self._bus_ref = bus_ref

    def take_turn(self, room_id: str, turn_id: str, player_id: str, text: str) -> dict[str, Any]:
        from api.schemas import TurnIn

        result = rooms.run_turn(
            deps.get_sessions(),
            self._bus_ref[0],
            room_id,
            TurnIn(turn_id=turn_id, player_id=player_id, text=text),
        )
        return result.as_api()


class KernelAuditTail:
    """`AuditSource` for the hub: mirrors the kernel chain onto the board."""

    def recent(self, limit: int) -> list[Mapping[str, Any]]:
        return [e.model_dump(mode="json") for e in deps.get_kernel().audit.tail(limit)]


def create_app() -> FastAPI:
    bus_ref: list[EventBus] = []
    hub = RoomHub(taker=SessionTurnTaker(bus_ref), audit=KernelAuditTail())
    bus = EventBus(hub)
    bus_ref.append(bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        bus.bind_loop(asyncio.get_running_loop())
        settings = deps.get_settings()
        set_stt(make_stt(settings.env))
        log.info(
            "api.start",
            extra={
                "demo_mode": settings.demo_mode,
                "ops_token": "set" if settings.ops_token_set else "unset",
                "room": settings.room_backend,
            },
        )
        yield
        set_stt(None)

    app = FastAPI(title="Second Key kernel", version="0.2.0", lifespan=lifespan)
    app.state.hub = hub
    app.state.bus = bus

    app.add_middleware(
        CORSMiddleware,
        allow_origins=deps.get_settings().cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],  # includes X-Ops-Token and X-Player-Token
    )

    # ---------------------------------------------------------------- error shapes

    @app.exception_handler(deps.OpsRefused)
    async def _ops(_: Request, exc: deps.OpsRefused) -> JSONResponse:
        return JSONResponse({"refused": True, "reason": "ops token required"}, status_code=401)

    @app.exception_handler(Refusal)
    async def _refusal(_: Request, exc: Refusal) -> JSONResponse:
        return JSONResponse(
            {"refused": True, "invariant": exc.invariant.value, "text": exc.text},
            status_code=409,
        )

    @app.exception_handler(IllegalTransition)
    async def _illegal(_: Request, exc: IllegalTransition) -> JSONResponse:
        return JSONResponse(
            {
                "refused": True,
                "invariant": "ILLEGAL_TRANSITION",
                "text": f"SETTLEMENT REFUSED · ILLEGAL_TRANSITION ({exc.state.value})",
            },
            status_code=409,
        )

    @app.exception_handler(RailError)
    async def _rail(_: Request, exc: RailError) -> JSONResponse:
        # Release rolled back; the certificate is still valid for a retry.
        return JSONResponse(
            {
                "refused": True,
                "invariant": "RAIL_FAILED",
                "text": "SETTLEMENT REFUSED · RAIL_FAILED",
            },
            status_code=502,
        )

    @app.exception_handler(KeyError)
    async def _missing(_: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            {"error": "not found", "key": str(exc.args[0]) if exc.args else ""}, 404
        )

    @app.exception_handler(ValueError)
    async def _bad(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # ---------------------------------------------------------------- routes

    app.include_router(payments.router)
    app.include_router(rooms.router)
    app.include_router(attack.router)
    app.include_router(audit.router)
    app.include_router(evalres.router)
    app.include_router(voice_router)
    app.include_router(make_router(hub))

    @app.get("/health")
    def health() -> dict[str, Any]:
        settings = deps.get_settings()
        return {
            "ok": True,
            "mode": deps.modes(),
            "policy_version": deps.get_kernel().policy_version,
            "demo_mode": settings.demo_mode,
            "ops_token": "set" if settings.ops_token_set else "unset",
        }

    return app


app = create_app()
