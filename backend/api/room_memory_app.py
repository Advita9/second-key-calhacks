"""Tiny FastAPI app that mounts only the memory-mode room router.

Used by tests/e2e/test_room.sh (memory branch) and by anyone who wants the room
without the rest of the kernel:

    cd backend && uv run uvicorn api.room_memory_app:app --port 8011

The lead wires `make_router(hub)` into api.main with the real TurnTaker; this
factory keeps the StubTurnTaker so it runs with nothing else present.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.room_ws import RoomHub, StubTurnTaker, TurnTaker, make_router


def create_app(taker: TurnTaker | None = None, hub: RoomHub | None = None) -> FastAPI:
    hub = hub or RoomHub(taker=taker or StubTurnTaker())
    app = FastAPI(title="Second Key room (memory mode)", version="0.1.0")
    app.state.room_hub = hub
    app.include_router(make_router(hub))

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "mode": {"room": "memory"}, "room_backend": "memory"}

    return app


app = create_app()
