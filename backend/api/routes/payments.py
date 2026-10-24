"""Payments: create, read, attest, certificate, release, mutate (demo), deny (operator cancel).

All sync `def` routes: FastAPI runs them in the threadpool, so a 7 s extractor call in
`create_payment` blocks one worker, not the loop. Refusals propagate as `Refusal` and the app
handler turns them into 409 bodies.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api import deps
from api.hub import EventBus
from api.schemas import (
    AttestIn,
    CertificateIn,
    DenyIn,
    MutateIn,
    PaymentCreate,
    ReleaseIn,
    payment_dict,
    payment_summary,
)
from kernel.llm.types import EvidenceItem
from kernel.models import AccountContext, Capability
from kernel.service import Kernel

log = logging.getLogger("second_key.api.payments")

router = APIRouter(tags=["payments"])

Bus = Annotated[EventBus, Depends(deps.get_bus)]
OpsToken = deps.OpsHeader


def _resolve(
    body: PaymentCreate,
) -> tuple[AccountContext, tuple[EvidenceItem, ...]]:
    """Context and transcript for a new payment: explicit body > room named by
    conversation_id > defaults (L-01 context, empty transcript)."""
    sessions = deps.get_sessions()
    ctx = body.account_context.to_ctx() if body.account_context else None
    conv: tuple[EvidenceItem, ...] | None = (
        tuple(e.to_item() for e in body.conversation) if body.conversation is not None else None
    )
    room_key = body.conversation_id.removeprefix("room_").strip()
    if room_key and (ctx is None or conv is None):
        room = next((r for r in sessions.rooms() if r.id == room_key.upper()), None)
        if room is not None:
            ctx = ctx or room.ctx
            conv = conv if conv is not None else tuple(room.history)
    return ctx or sessions.default_ctx, conv or ()


@router.post("/payments")
def create_payment(body: PaymentCreate, bus: Bus) -> dict[str, Any]:
    kernel = deps.get_kernel()
    p_in = body.to_payment_in()
    ctx, conv = _resolve(body)
    payment, decision = kernel.create_payment(p_in, ctx, conv)
    deps.remember_context(payment.id, ctx)
    record = kernel.get(payment.id)
    bus.payment(record)
    return payment_summary(record)


@router.get("/payments")
def list_payments(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict[str, Any]:
    """Not in docs/api.md; the /ops queue reads it. Newest first."""
    records = deps.get_kernel().list_payments(limit)
    return {"payments": [payment_dict(r) for r in records]}


@router.get("/payments/{payment_id}")
def get_payment(payment_id: str) -> dict[str, Any]:
    return payment_dict(deps.get_kernel().get(payment_id))


@router.post("/payments/{payment_id}/attest")
def attest(
    payment_id: str, body: AttestIn, bus: Bus, x_ops_token: OpsToken = None
) -> dict[str, Any]:
    cap = body.cap()
    if deps.attest_needs_ops(cap):
        deps.check_ops(x_ops_token)
    kernel = deps.get_kernel()
    try:
        kernel.attest(payment_id, body.actor_id, cap, body.note)
    finally:
        _publish_if_exists(kernel, bus, payment_id)
    record = kernel.get(payment_id)
    return {
        "state": record.payment.state.value,
        "fingerprint": record.payment.fingerprint,
        "attestations": payment_dict(record)["attestations"],
        **payment_dict(record),
    }


@router.post("/payments/{payment_id}/certificate")
def certificate(
    payment_id: str, body: CertificateIn, bus: Bus, x_ops_token: OpsToken = None
) -> dict[str, Any]:
    deps.check_ops(x_ops_token)
    kernel = deps.get_kernel()
    try:
        cert = kernel.issue_certificate(payment_id, body.actor_id, body.cap())
    finally:
        _publish_if_exists(kernel, bus, payment_id)
    return {
        "certificate": {
            "id": cert.id,
            "payment_id": cert.payment_id,
            "fingerprint": cert.fingerprint,
            "policy_version": cert.policy_version,
            "nonce": cert.nonce,
            "expires_at": cert.expires_at.isoformat(),
        }
    }


@router.post("/payments/{payment_id}/release")
def release(
    payment_id: str, body: ReleaseIn, bus: Bus, x_ops_token: OpsToken = None
) -> dict[str, Any]:
    deps.check_ops(x_ops_token)
    kernel = deps.get_kernel()
    try:
        payment = kernel.release(payment_id, body.certificate_id, body.nonce)
    finally:
        _publish_if_exists(kernel, bus, payment_id)
    return {
        "state": payment.state.value,
        "nessie_transfer_id": payment.nessie_transfer_id,
        "fingerprint": payment.fingerprint,
        "id": payment.id,
    }


@router.post("/payments/{payment_id}/mutate")
def mutate(
    payment_id: str, body: MutateIn, bus: Bus, x_ops_token: OpsToken = None
) -> dict[str, Any]:
    if not deps.get_settings().demo_mode:
        raise HTTPException(status_code=404, detail="not found")
    deps.check_ops(x_ops_token)
    kernel = deps.get_kernel()
    ctx = body.account_context.to_ctx() if body.account_context else deps.context_for(payment_id)
    patch = body.patch()
    if not patch:
        raise HTTPException(status_code=400, detail="mutate: empty patch")
    try:
        kernel.mutate(payment_id, patch, ctx)
    finally:
        _publish_if_exists(kernel, bus, payment_id)
    deps.remember_context(payment_id, ctx)
    return payment_summary(kernel.get(payment_id))


@router.post("/payments/{payment_id}/deny")
def deny(payment_id: str, body: DenyIn, bus: Bus, x_ops_token: OpsToken = None) -> dict[str, Any]:
    """Operator cancel: the payment goes to CANCELLED, every attestation and certificate on it
    is voided. DENIED and SUBMITTED are terminal and refuse."""
    deps.check_ops(x_ops_token)
    kernel = deps.get_kernel()
    try:
        kernel.cancel(payment_id, body.actor_id, Capability.BANK_REVIEW, body.note)
    finally:
        _publish_if_exists(kernel, bus, payment_id)
    record = kernel.get(payment_id)
    return {"state": record.payment.state.value, **payment_dict(record)}


def _publish_if_exists(kernel: Kernel, bus: EventBus, payment_id: str) -> None:
    try:
        bus.payment(kernel.get(payment_id))
    except KeyError:
        return
