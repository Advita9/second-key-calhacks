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
from pathlib import Path
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
from kernel.audit import AuditChainError
from kernel.llm.cache import default_cache_root as llm_cache_root
from kernel.models import Refusal
from kernel.rail import RailError
from kernel.state import IllegalTransition
from kernel.voice.cache import default_cache_root as audio_cache_root
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


def cache_counts(env: Mapping[str, str]) -> dict[str, int]:
    """`/health.cache`: entries on disk in the LLM and audio caches. One listing each."""

    def n(root: Path, pattern: str) -> int:
        try:
            return sum(1 for _ in root.glob(pattern))
        except OSError:
            return 0

    return {
        "llm_entries": n(llm_cache_root(env), "*.json"),
        "audio_entries": n(audio_cache_root(dict(env)), "*.wav"),
    }


def audit_status() -> dict[str, Any]:
    """`/health.audit`: chain verification summary. Reports a mismatch, never raises."""
    try:
        v = deps.get_kernel().audit_verify()
    except Exception as e:  # noqa: BLE001  health must answer even when the log is broken
        return {"ok": False, "anchor": "error", "error": type(e).__name__}
    return {
        "ok": v.ok,
        "length": v.length,
        "anchor": v.anchor,
        "first_bad_seq": v.first_bad_seq,
        "hint": v.hint,
    }


def _authorize_room_role(role: str, token: str | None) -> bool:
    """Board and ops room views need the ops token when one is configured."""
    return role == "attacker" or deps.ops_ok(token)


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

    @app.exception_handler(AuditChainError)
    async def _chain(_: Request, exc: AuditChainError) -> JSONResponse:
        # The audit table was altered while the kernel was down; appends are blocked until an
        # operator calls POST /audit/acknowledge. Report, never write.
        return JSONResponse(
            {
                "refused": True,
                "invariant": "AUDIT_ANCHOR_MISMATCH",
                "text": "SETTLEMENT REFUSED · AUDIT_ANCHOR_MISMATCH",
            },
            status_code=503,
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

    @app.exception_handler(deps.NotFound)
    async def _missing(_: Request, exc: deps.NotFound) -> JSONResponse:
        return JSONResponse({"error": f"{exc.what} not found", "key": exc.key}, status_code=404)

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
    app.include_router(make_router(hub, authorize=_authorize_room_role))

    @app.get("/health")
    def health() -> dict[str, Any]:
        settings = deps.get_settings()
        return {
            "ok": True,
            "mode": deps.modes(),
            "policy_version": deps.get_kernel().policy_version,
            "demo_mode": settings.demo_mode,
            "ops_token": "set" if settings.ops_token_set else "unset",
            "cache": cache_counts(settings.env),
            "audit": audit_status(),
        }

    return app


app = create_app()
