"""Kernel WS fan-out. Reuses `RoomHub.broadcast_event` (the `/ws` endpoint lives in
`api/room_ws.py`); this wrapper makes it safe to publish from sync routes running in the
threadpool by hopping onto the event loop with `call_soon_threadsafe`.

Messages (docs/api.md):
  {type: "payment", payment_id, state, fingerprint, reasons[], last_refusal, amount_cents,
   beneficiary: {name, account_ref}, rail}        (board and ops sockets only)
  {type: "margaret", room_id, text, audio_url, persuaded}
  {type: "attack", name, invariant}
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Mapping
from typing import Any

from api.room_ws import RoomHub
from kernel.service import PaymentRecord

log = logging.getLogger("second_key.api.ws")


class EventBus:
    def __init__(self, hub: RoomHub) -> None:
        self.hub = hub
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._loop_thread = threading.get_ident()

    def publish(self, event: Mapping[str, Any]) -> None:
        """Never raises: a WS fan-out problem must not mask the kernel result it follows."""
        try:
            self._publish(dict(event))
        except Exception as e:  # noqa: BLE001
            log.warning("ws.publish.failed", extra={"error": type(e).__name__})

    def _publish(self, payload: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                log.debug("ws.publish.no_loop", extra={"type": payload.get("type")})
                return
            self.hub.broadcast_event(payload)
            return
        if threading.get_ident() == self._loop_thread:
            self.hub.broadcast_event(payload)
        else:
            loop.call_soon_threadsafe(self.hub.broadcast_event, payload)

    # ---------------------------------------------------------------- helpers

    def payment(self, record: PaymentRecord, last_refusal: str | None = None) -> None:
        self.publish(payment_event(record, last_refusal))

    def attack(self, name: str, invariant: str | None) -> None:
        self.publish({"type": "attack", "name": name, "invariant": invariant})

    def margaret(
        self, room_id: str, text: str, audio_url: str | None, persuaded: bool, **extra: Any
    ) -> None:
        self.publish(
            {
                "type": "margaret",
                "room_id": room_id,
                "text": text,
                "audio_url": audio_url,
                "persuaded": persuaded,
                **extra,
            }
        )


def last_refusal_of(record: PaymentRecord) -> str | None:
    for ev in reversed(record.history):
        if ev.kind == "REFUSED":
            inv = ev.payload.get("invariant")
            return str(inv) if inv is not None else None
    return None


def payment_event(record: PaymentRecord, last_refusal: str | None = None) -> dict[str, Any]:
    p = record.payment
    return {
        "type": "payment",
        "payment_id": p.id,
        "state": p.state.value,
        "fingerprint": p.fingerprint,
        "reasons": list(record.decision.rule_ids) if record.decision else [],
        "last_refusal": last_refusal if last_refusal is not None else last_refusal_of(record),
        "amount_cents": p.amount_cents,
        "beneficiary": {"name": p.beneficiary.name, "account_ref": p.beneficiary.account_ref},
        "rail": p.rail.value,
    }
