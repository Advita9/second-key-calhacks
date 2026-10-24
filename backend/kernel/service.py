"""`Kernel`: the facade every caller (API, eval, demo, property tests) goes through.

Responsibilities, in order of importance:
- Only this module turns a policy `Decision` into a state `Event` (`_apply_decision`).
- The extractor runs OUTSIDE the lock and its result is only data; any failure or timeout
  gives `fail_closed(decision, "X-00")`.
- `release` verifies the certificate in a fixed order, then consumes it, submits to the rail
  and transitions inside one BEGIN IMMEDIATE. The rail failing rolls everything back.
- Every refusal is audited as kind REFUSED before the `Refusal` is raised.
- An RLock serialises every public method; SQLite sees one writer at a time.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn, assert_never

from pydantic import BaseModel, ConfigDict, ValidationError

from kernel import attest as attest_mod
from kernel import certs as certs_mod
from kernel.audit import AuditEvent, AuditLog, VerifyResult
from kernel.clock import Clock, SystemClock
from kernel.db import connect, immediate, insert_payment, load_payment, update_payment_fields
from kernel.fingerprint import fingerprint
from kernel.llm.types import EvidenceItem, Extractor, ExtractorResult, NullExtractor, Signal
from kernel.models import (
    AccountContext,
    Attestation,
    Capability,
    Certificate,
    Decision,
    Invariant,
    Payment,
    PaymentIn,
    Refusal,
    State,
)
from kernel.policy.engine import EXTRACTOR_FAIL_RULE_ID, Policy, decide, fail_closed
from kernel.rail import NullTransferRail, RailError, TransferRail
from kernel.state import (
    Decided,
    HoldLifted,
    IllegalTransition,
    Mutated,
    Released,
    Submitted,
    transition,
)

log = logging.getLogger("second_key.kernel")

SYSTEM_ACTOR = "system"
_TERMINAL = (State.SUBMITTED, State.CANCELLED)


class PaymentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    payment: Payment
    decision: Decision | None
    signals: tuple[Signal, ...]
    attestations: list[Attestation]
    certificates: list[Certificate]  # nonces redacted
    history: list[AuditEvent]


# Commands for traces (property tests, demo). Frozen dataclasses mirroring the method args.


@dataclass(frozen=True)
class Create:
    payment: PaymentIn
    ctx: AccountContext
    conversation: tuple[EvidenceItem, ...] = ()


@dataclass(frozen=True)
class Attest:
    payment_id: str
    actor_id: str
    capability: Capability
    note: str | None = None


@dataclass(frozen=True)
class IssueCert:
    payment_id: str
    actor_id: str
    capability: Capability


@dataclass(frozen=True)
class Release:
    payment_id: str
    certificate_id: str
    nonce: str


@dataclass(frozen=True)
class Mutate:
    payment_id: str
    patch: Mapping[str, Any]
    ctx: AccountContext


@dataclass(frozen=True)
class Tick:
    seconds: float


Cmd = Create | Attest | IssueCert | Release | Mutate | Tick


@dataclass(frozen=True)
class CmdResult:
    ok: bool
    invariant: Invariant | None = None
    payment: Payment | None = None
    certificate: Certificate | None = None
    decision: Decision | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Kernel:
    def __init__(
        self,
        db_path: str = ":memory:",
        *,
        policy: Policy,
        clock: Clock | None = None,
        extractor: Extractor | None = None,
        rail: TransferRail | None = None,
        cert_ttl_s: int = 120,
        extractor_timeout_s: float = 8.0,
    ) -> None:
        self.policy = policy
        self.clock: Clock = clock if clock is not None else SystemClock()
        self.extractor: Extractor = extractor if extractor is not None else NullExtractor()
        self.rail: TransferRail = rail if rail is not None else NullTransferRail()
        self.cert_ttl_s = cert_ttl_s
        self.extractor_timeout_s = extractor_timeout_s
        self.conn = connect(db_path)
        self.audit = AuditLog(self.conn, self.clock)
        self._lock = threading.RLock()
        # Per-payment data that is not part of the money-moving record.
        self._conversations: dict[str, tuple[EvidenceItem, ...]] = {}
        self._signals: dict[str, tuple[Signal, ...]] = {}
        self._decisions: dict[str, Decision] = {}

    @property
    def policy_version(self) -> str:
        return self.policy.version

    # ---------------------------------------------------------------- public API

    def create_payment(
        self,
        p: PaymentIn,
        ctx: AccountContext,
        conversation: Sequence[EvidenceItem] = (),
    ) -> tuple[Payment, Decision]:
        conv = tuple(conversation)
        extracted, extractor_ok = self._extract(conv, p)  # outside the lock: data only
        with self._lock:
            payment = Payment(
                **p.model_dump(),
                id=f"pay_{secrets.token_hex(8)}",
                state=State.DRAFT,
                fingerprint=fingerprint(p, self.policy.version),
                policy_version=self.policy.version,
                created_at=self.clock.now(),
            )
            insert_payment(self.conn, payment)
            self._conversations[payment.id] = conv
            self.audit.append(
                SYSTEM_ACTOR,
                "CREATED",
                {"payment_id": payment.id, "fingerprint": payment.fingerprint},
            )
            payment = transition(payment, Submitted(), audit=self.audit, actor=SYSTEM_ACTOR)
            payment, decision = self._decide_and_apply(payment, ctx, extracted, extractor_ok)
        log.info(
            "payment.created",
            extra={
                "payment_id": payment.id,
                "state": payment.state.value,
                "outcome": decision.outcome.value,
                "rule_ids": list(decision.rule_ids),
            },
        )
        return payment, decision

    def attest(
        self,
        payment_id: str,
        actor_id: str,
        capability: Capability,
        note: str | None = None,
    ) -> Payment:
        actor = f"{capability.value}:{actor_id}"
        with self._lock:
            payment = self._load(payment_id)
            self._refuse_if_terminal(payment, actor, "attest")
            conflict = attest_mod.conflict(payment, actor_id)
            if conflict is not None:
                self._refuse(payment, actor, conflict, "attest", reason="ACTOR_IS_BENEFICIARY")
            att = attest_mod.insert(
                self.conn,
                self.clock,
                payment=payment,
                actor_id=actor_id,
                capability=capability,
                note=note,
            )
            self.audit.append(
                actor,
                "ATTESTED",
                {
                    "payment_id": payment.id,
                    "attestation_id": att.id,
                    "capability": capability.value,
                    "fingerprint": payment.fingerprint,
                    "has_note": note is not None,
                },
            )
            if payment.state is State.HELD and capability in attest_mod.CAN_LIFT_HOLD:
                payment = transition(payment, HoldLifted(), audit=self.audit, actor=actor)
        log.info(
            "payment.attested",
            extra={
                "payment_id": payment.id,
                "capability": capability.value,
                "state": payment.state.value,
            },
        )
        return payment

    def issue_certificate(
        self, payment_id: str, actor_id: str, capability: Capability
    ) -> Certificate:
        actor = f"{capability.value}:{actor_id}"
        with self._lock:
            payment = self._load(payment_id)
            if payment.state is State.DENIED:
                self._refuse(payment, actor, Invariant.I6_DENIED, "issue_certificate")
            if payment.state is not State.ELIGIBLE_TO_SUBMIT:
                self._refuse(
                    payment,
                    actor,
                    Invariant.I1_NOT_ELIGIBLE,
                    "issue_certificate",
                    reason=f"STATE_{payment.state.value}",
                )
            if capability not in attest_mod.CAN_ISSUE_CERT:
                self._refuse(
                    payment,
                    actor,
                    Invariant.I1_NOT_ELIGIBLE,
                    "issue_certificate",
                    reason="CERT_REFUSED_CAPABILITY",
                )
            conflict = attest_mod.conflict(payment, actor_id)
            if conflict is not None:
                self._refuse(
                    payment, actor, conflict, "issue_certificate", reason="ACTOR_IS_BENEFICIARY"
                )
            cert = certs_mod.issue(
                self.conn,
                self.clock,
                payment=payment,
                actor_id=actor_id,
                capability=capability,
                ttl_s=self.cert_ttl_s,
            )
            self.audit.append(
                actor,
                "CERT_ISSUED",
                {
                    "payment_id": payment.id,
                    "certificate_id": cert.id,
                    "fingerprint": cert.fingerprint,
                    "policy_version": cert.policy_version,
                    "expires_at": cert.expires_at,
                },
            )
        log.info("cert.issued", extra={"payment_id": payment.id, "certificate_id": cert.id})
        return cert

    def release(self, payment_id: str, certificate_id: str, nonce: str) -> Payment:
        actor = f"release:{certificate_id}"
        with self._lock:
            payment = self._load(payment_id)
            if payment.state is State.DENIED:
                self._refuse(payment, actor, Invariant.I6_DENIED, "release")
            cert = certs_mod.get(self.conn, certificate_id)
            if cert is None:
                self._refuse(payment, actor, Invariant.I1_NO_CERT, "release", reason="NO_SUCH_CERT")
            now = self.clock.now()
            failed = certs_mod.verify(cert, payment, nonce, now)
            if failed is not None:
                self._refuse(payment, actor, failed, "release", certificate_id=cert.id)
            try:
                with immediate(self.conn):
                    if not certs_mod.consume(self.conn, cert.id, payment.fingerprint, now):
                        raise Refusal(Invariant.I3_REPLAY, "consume affected no row")
                    self.audit.append(
                        actor,
                        "CERT_CONSUMED",
                        {"payment_id": payment.id, "certificate_id": cert.id},
                    )
                    try:
                        transfer_id = self.rail.submit(payment, cert)
                    except Exception as e:  # noqa: BLE001  any rail failure rolls back
                        raise RailError(f"{type(e).__name__}: {e}") from e
                    payment = transition(
                        payment,
                        Released(certificate_id=cert.id, transfer_id=transfer_id),
                        audit=self.audit,
                        actor=actor,
                    )
            except Refusal as r:
                # Transaction rolled back; record the refusal outside it.
                self._refuse(payment, actor, r.invariant, "release", certificate_id=cert.id)
            except RailError as e:
                self.audit.append(
                    actor,
                    "RAIL_FAILED",
                    {"payment_id": payment.id, "certificate_id": cert.id, "error": str(e)},
                )
                log.error("rail.failed", extra={"payment_id": payment.id, "error": str(e)})
                raise
        log.info(
            "payment.released",
            extra={"payment_id": payment.id, "certificate_id": cert.id, "transfer_id": transfer_id},
        )
        return payment

    def mutate(
        self, payment_id: str, patch: Mapping[str, Any], ctx: AccountContext
    ) -> tuple[Payment, Decision]:
        actor = "mutate"
        with self._lock:
            payment = self._load(payment_id)
            self._refuse_if_terminal(payment, actor, "mutate")
            new_in = _apply_patch(payment, patch)
            conv = self._conversations.get(payment.id, ())
            state_before = payment.state
        extracted, extractor_ok = self._extract(conv, new_in)  # outside the lock
        with self._lock:
            payment = self._load(payment_id)
            if payment.state is not state_before:
                self._refuse(
                    payment, actor, Invariant.I1_NOT_ELIGIBLE, "mutate", reason="STATE_CHANGED"
                )
            new_fp = fingerprint(new_in, self.policy.version)
            now = self.clock.now()
            with immediate(self.conn):
                patched = payment.model_copy(
                    update={k: getattr(new_in, k) for k in PaymentIn.model_fields}
                )
                update_payment_fields(self.conn, patched)
                voided_att = attest_mod.void_all_for_payment(self.conn, payment.id, now)
                voided_cert = certs_mod.void_all_for_payment(self.conn, payment.id, now)
                self.audit.append(
                    actor,
                    "VOIDED",
                    {
                        "payment_id": payment.id,
                        "attestations": voided_att,
                        "certificates": voided_cert,
                        "old_fingerprint": payment.fingerprint,
                        "new_fingerprint": new_fp,
                        "fields": sorted(patch),
                    },
                )
                payment = transition(
                    patched, Mutated(new_fingerprint=new_fp), audit=self.audit, actor=actor
                )
                payment, decision = self._decide_and_apply(payment, ctx, extracted, extractor_ok)
        log.info(
            "payment.mutated",
            extra={
                "payment_id": payment.id,
                "state": payment.state.value,
                "outcome": decision.outcome.value,
            },
        )
        return payment, decision

    def get(self, payment_id: str) -> PaymentRecord:
        with self._lock:
            payment = self._load(payment_id)
            rows = self.conn.execute(
                "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit "
                "WHERE json_extract(payload, '$.payment_id') = ? ORDER BY seq",
                (payment_id,),
            ).fetchall()
            history = [self._audit_row(r) for r in rows]
            return PaymentRecord(
                payment=payment,
                decision=self._decisions.get(payment_id),
                signals=self._signals.get(payment_id, ()),
                attestations=attest_mod.list_for_payment(self.conn, payment_id),
                certificates=[
                    certs_mod.redact(c) for c in certs_mod.list_for_payment(self.conn, payment_id)
                ],
                history=history,
            )

    def audit_verify(self) -> VerifyResult:
        with self._lock:
            return self.audit.verify()

    def apply(self, cmd: Cmd) -> CmdResult:
        """Never raises. For random traces and the demo script."""
        try:
            if isinstance(cmd, Create):
                p, d = self.create_payment(cmd.payment, cmd.ctx, cmd.conversation)
                return CmdResult(ok=True, payment=p, decision=d)
            if isinstance(cmd, Attest):
                p = self.attest(cmd.payment_id, cmd.actor_id, cmd.capability, cmd.note)
                return CmdResult(ok=True, payment=p)
            if isinstance(cmd, IssueCert):
                c = self.issue_certificate(cmd.payment_id, cmd.actor_id, cmd.capability)
                return CmdResult(ok=True, certificate=c)
            if isinstance(cmd, Release):
                p = self.release(cmd.payment_id, cmd.certificate_id, cmd.nonce)
                return CmdResult(ok=True, payment=p)
            if isinstance(cmd, Mutate):
                p, d = self.mutate(cmd.payment_id, cmd.patch, cmd.ctx)
                return CmdResult(ok=True, payment=p, decision=d)
            if isinstance(cmd, Tick):
                advance = getattr(self.clock, "advance", None)
                if advance is None:
                    return CmdResult(ok=False, error="clock is not a FakeClock")
                advance(cmd.seconds)
                return CmdResult(ok=True)
            assert_never(cmd)
        except Refusal as r:
            return CmdResult(ok=False, invariant=r.invariant, error=r.text)
        except (KeyError, ValueError, IllegalTransition, RailError) as e:
            return CmdResult(ok=False, error=f"{type(e).__name__}: {e}")

    # ---------------------------------------------------------------- internals

    def _load(self, payment_id: str) -> Payment:
        return load_payment(self.conn, payment_id)

    def _refuse(
        self,
        payment: Payment,
        actor: str,
        invariant: Invariant,
        action: str,
        **extra: object,
    ) -> NoReturn:
        payload: dict[str, object] = {
            "payment_id": payment.id,
            "action": action,
            "invariant": invariant.value,
            "state": payment.state.value,
            **extra,
        }
        self.audit.append(actor, "REFUSED", payload)
        log.info(
            "kernel.refused",
            extra={"payment_id": payment.id, "action": action, "invariant": invariant.value},
        )
        raise Refusal(invariant)

    def _refuse_if_terminal(self, payment: Payment, actor: str, action: str) -> None:
        if payment.state is State.DENIED:
            self._refuse(payment, actor, Invariant.I6_DENIED, action)
        if payment.state in _TERMINAL:
            self._refuse(
                payment,
                actor,
                Invariant.I1_NOT_ELIGIBLE,
                action,
                reason=f"STATE_{payment.state.value}",
            )

    def _extract(
        self, conversation: tuple[EvidenceItem, ...], p: PaymentIn
    ) -> tuple[ExtractorResult, bool]:
        """Run the extractor with a timeout. Returns (result, ok). Never raises."""
        box: list[ExtractorResult] = []
        errors: list[str] = []

        def run() -> None:
            try:
                out = self.extractor.extract(conversation, p)
                if not isinstance(out, ExtractorResult):
                    raise TypeError(f"extractor returned {type(out).__name__}")
                box.append(out)
            except Exception as e:  # noqa: BLE001  model output is untrusted; fail closed
                errors.append(f"{type(e).__name__}: {e}")

        t = threading.Thread(target=run, name="extractor", daemon=True)
        t.start()
        t.join(self.extractor_timeout_s)
        if t.is_alive():
            errors.append(f"timeout after {self.extractor_timeout_s}s")
        if box and not errors:
            return box[0], True
        log.warning("extractor.failed", extra={"error": errors[0] if errors else "no result"})
        return ExtractorResult(), False

    def _decide_and_apply(
        self,
        payment: Payment,
        ctx: AccountContext,
        extracted: ExtractorResult,
        extractor_ok: bool,
    ) -> tuple[Payment, Decision]:
        """PENDING_REVIEW -> decided state. The only place a Decision becomes an Event."""
        p_in = PaymentIn.model_validate(payment.model_dump(include=set(PaymentIn.model_fields)))
        if extractor_ok:
            self.audit.append(
                SYSTEM_ACTOR,
                "EXTRACTED",
                {
                    "payment_id": payment.id,
                    "signals": [s.model_dump() for s in extracted.signals],
                    "summary": extracted.summary,
                },
            )
        else:
            self.audit.append(
                SYSTEM_ACTOR,
                "EXTRACTOR_FAILED",
                {"payment_id": payment.id, "rule_id": EXTRACTOR_FAIL_RULE_ID},
            )
        decision = decide(p_in, extracted.signals, ctx, self.policy)
        if not extractor_ok:
            decision = fail_closed(decision, EXTRACTOR_FAIL_RULE_ID)
        self._signals[payment.id] = extracted.signals
        self._decisions[payment.id] = decision
        payment = transition(
            payment,
            Decided(outcome=decision.outcome, rule_ids=decision.rule_ids),
            audit=self.audit,
            actor=SYSTEM_ACTOR,
        )
        return payment, decision

    @staticmethod
    def _audit_row(r: tuple[Any, ...]) -> AuditEvent:
        import json

        return AuditEvent(
            seq=r[0],
            ts=r[1],
            actor=r[2],
            kind=r[3],
            payload=json.loads(r[4]),
            prev_hash=r[5],
            hash=r[6],
        )


def _apply_patch(payment: Payment, patch: Mapping[str, Any]) -> PaymentIn:
    """Merge a partial PaymentIn over the current one. Unknown keys and bad values raise."""
    allowed = set(PaymentIn.model_fields)
    unknown = set(patch) - allowed
    if unknown:
        raise ValueError(f"mutate: unknown field(s) {sorted(unknown)}")
    base: dict[str, Any] = payment.model_dump(include=allowed)
    for k, v in patch.items():
        if k == "beneficiary" and isinstance(v, Mapping):
            base["beneficiary"] = {**base["beneficiary"], **dict(v)}
        else:
            base[k] = v
    try:
        return PaymentIn.model_validate(base, strict=False)
    except ValidationError as e:
        raise ValueError(f"mutate: invalid patch: {e.errors()[0]['msg']}") from None
