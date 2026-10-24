"""Audit log: tail, verify, and the demo-only tamper."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api import deps
from api.schemas import audit_event_dict

log = logging.getLogger("second_key.api.audit")

router = APIRouter(tags=["audit"])


@router.get("/audit")
def tail(limit: Annotated[int, Query(ge=1, le=2000)] = 200) -> list[dict[str, Any]]:
    kernel = deps.get_kernel()
    return [audit_event_dict(e) for e in kernel.audit.tail(limit)]


@router.get("/audit/verify")
def verify() -> dict[str, Any]:
    return deps.get_kernel().audit_verify().model_dump(mode="json")


@router.post("/audit/tamper", dependencies=[Depends(deps.ops_guard)])
def tamper() -> dict[str, Any]:
    """DEMO ONLY: edit one past payload in place so `/audit/verify` goes red on stage."""
    if not deps.get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    kernel = deps.get_kernel()
    events = kernel.audit.tail(2000)
    if not events:
        raise HTTPException(status_code=409, detail="audit log is empty; nothing to tamper")
    target = events[len(events) // 2]
    kernel.audit.tamper(target.seq, {"tampered": True})
    result = kernel.audit_verify()
    log.warning("audit.tampered", extra={"seq": target.seq, "verify_ok": result.ok})
    return {"tampered_seq": target.seq, "verify": result.model_dump(mode="json")}
