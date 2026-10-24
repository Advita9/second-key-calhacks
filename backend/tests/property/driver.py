"""Runs a symbolic trace against one Kernel and keeps a shadow model for the oracles.

The shadow model never looks inside the kernel's tables to decide what *should* happen; it
only remembers what the kernel told us (ids, nonces, successful releases) and the clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from kernel.clock import FakeClock
from kernel.db import load_payment
from kernel.models import Capability, Invariant, Payment, Refusal, State
from kernel.service import (
    Attest,
    Cmd,
    CmdResult,
    Create,
    IssueCert,
    Kernel,
    Mutate,
    PaymentRecord,
    Release,
    Tick,
)
from tests.property.strategies import (
    BeneficiaryActor,
    SAttest,
    SCancel,
    SCreate,
    SIssueCert,
    SMutate,
    SRelease,
    STick,
    SymCmd,
)

NO_SUCH_PAYMENT = "pay_nope"


@dataclass(frozen=True)
class Cancel:
    """Not in `kernel.service.Cmd` yet; the driver calls `Kernel.cancel` behind `apply`'s
    never-raises contract."""

    payment_id: str
    actor_id: str
    note: str | None = None


TraceCmd = Cmd | Cancel
TERMINAL: frozenset[State] = frozenset({State.SUBMITTED, State.DENIED, State.CANCELLED})


@dataclass(frozen=True)
class CertInfo:
    id: str
    nonce: str
    payment_id: str
    fingerprint: str
    state_at_issue: State
    expires_at: datetime
    epoch: int  # number of successful mutations on the payment when issued


@dataclass
class Step:
    sym: SymCmd
    cmd: TraceCmd
    result: CmdResult
    payment_id: str | None
    payment_before: Payment | None
    payment_after: Payment | None
    now: datetime
    record_after: PaymentRecord | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def state_before(self) -> State | None:
        return self.payment_before.state if self.payment_before else None

    @property
    def state_after(self) -> State | None:
        return self.payment_after.state if self.payment_after else None


class Driver:
    def __init__(self, kernel: Kernel, clock: FakeClock, *, snapshot: bool = False) -> None:
        self.kernel = kernel
        self.clock = clock
        self.snapshot = snapshot
        self.payments: list[str] = []
        self.certs: list[CertInfo] = []
        self.cert_by_id: dict[str, CertInfo] = {}
        self.consumed: list[CertInfo] = []
        self.released: dict[str, str] = {}  # cert id -> nonce the successful Release used
        self.voided: set[str] = set()  # cert ids voided by mutate, cancel or a sibling release
        self.epoch: dict[str, int] = {}  # payment id -> successful mutation count
        self.steps: list[Step] = []

    # ---------------------------------------------------------------- resolution

    def pid(self, slot: int) -> str:
        if not self.payments:
            return NO_SUCH_PAYMENT
        return self.payments[slot % len(self.payments)]

    def load(self, payment_id: str) -> Payment | None:
        try:
            return load_payment(self.kernel.conn, payment_id)
        except KeyError:
            return None

    def _actor(self, actor: str | BeneficiaryActor, payment: Payment | None) -> str:
        if not isinstance(actor, BeneficiaryActor):
            return actor
        ref = payment.beneficiary.account_ref if payment else "ext_nobody"
        if actor.variant == "upper":
            return ref.upper()
        if actor.variant == "padded":
            return f" {ref} "
        if actor.variant == "zwsp":
            return ref + "\u200b"
        return ref

    def _cert(self, sym: SRelease, payment_id: str) -> tuple[str, CertInfo | None]:
        ref = sym.cert
        pool: list[CertInfo]
        if ref.kind == "own":
            pool = [c for c in self.certs if c.payment_id == payment_id]
        elif ref.kind == "any":
            pool = self.certs
        elif ref.kind == "consumed":
            pool = self.consumed
        else:
            pool = []
        if not pool:
            return ref.forged_id, None
        info = pool[ref.index % len(pool)]
        return info.id, info

    def _nonce(self, sym: SRelease, info: CertInfo | None) -> str:
        ref = sym.nonce
        if ref.kind == "real" and info is not None:
            return info.nonce
        if ref.kind == "other" and self.certs:
            return self.certs[ref.index % len(self.certs)].nonce
        if ref.kind == "empty":
            return ""
        return ref.wrong

    def resolve(self, sym: SymCmd) -> tuple[TraceCmd, str | None, dict[str, Any]]:
        if isinstance(sym, SCreate):
            return Create(sym.payment, sym.ctx, sym.conversation), None, {}
        if isinstance(sym, STick):
            return Tick(sym.seconds), None, {}
        pid = self.pid(sym.slot)
        payment = self.load(pid)
        if isinstance(sym, SAttest):
            actor = self._actor(sym.actor, payment)
            return Attest(pid, actor, sym.capability, sym.note), pid, {}
        if isinstance(sym, SIssueCert):
            actor = self._actor(sym.actor, payment)
            return IssueCert(pid, actor, sym.capability), pid, {}
        if isinstance(sym, SRelease):
            cert_id, info = self._cert(sym, pid)
            nonce = self._nonce(sym, info)
            return Release(pid, cert_id, nonce), pid, {"cert": info}
        if isinstance(sym, SMutate):
            return Mutate(pid, sym.patch, sym.ctx), pid, {}
        if isinstance(sym, SCancel):
            return Cancel(pid, sym.actor), pid, {}
        raise TypeError(sym)

    def _apply(self, cmd: TraceCmd) -> CmdResult:
        if not isinstance(cmd, Cancel):
            return self.kernel.apply(cmd)
        try:
            p = self.kernel.cancel(cmd.payment_id, cmd.actor_id, Capability.BANK_REVIEW, cmd.note)
            return CmdResult(ok=True, payment=p)
        except Refusal as r:
            return CmdResult(ok=False, invariant=r.invariant, error=r.text)
        except Exception as e:  # noqa: BLE001  mirror apply's never-raises boundary
            return CmdResult(ok=False, error=f"{type(e).__name__}: {e}")

    def _void_certs(self, payment_id: str, keep: str | None = None) -> None:
        for c in self.certs:
            if c.payment_id == payment_id and c.id != keep:
                self.voided.add(c.id)

    # ---------------------------------------------------------------- execution

    def step(self, sym: SymCmd) -> Step:
        cmd, pid, extra = self.resolve(sym)
        before = self.load(pid) if pid else None
        now = self.clock.now()
        if isinstance(cmd, Release):
            extra["epoch_before"] = self.epoch.get(pid or "", 0)
            extra["released_before"] = frozenset(self.released)
            extra["voided_before"] = frozenset(self.voided)
        result = self._apply(cmd)
        if isinstance(cmd, Create) and result.ok and result.payment is not None:
            pid = result.payment.id
            self.payments.append(pid)
            self.epoch[pid] = 0
        if isinstance(cmd, IssueCert) and result.ok and result.certificate is not None:
            c = result.certificate
            info = CertInfo(
                id=c.id,
                nonce=c.nonce,
                payment_id=c.payment_id,
                fingerprint=c.fingerprint,
                state_at_issue=before.state if before else State.DRAFT,
                expires_at=c.expires_at,
                epoch=self.epoch.get(c.payment_id, 0),
            )
            self.certs.append(info)
            self.cert_by_id[info.id] = info
        if isinstance(cmd, Release) and result.ok:
            info = self.cert_by_id[cmd.certificate_id]
            self.consumed.append(info)
            self.released[cmd.certificate_id] = cmd.nonce
            self._void_certs(info.payment_id, keep=info.id)  # siblings die with the release
        if isinstance(cmd, Mutate) and result.ok and pid is not None:
            self.epoch[pid] = self.epoch.get(pid, 0) + 1
            self._void_certs(pid)
        if isinstance(cmd, Cancel) and result.ok and pid is not None:
            self._void_certs(pid)
        after = self.load(pid) if pid else None
        record = None
        if self.snapshot and pid is not None and after is not None:
            record = self.kernel.get(pid)
        step = Step(
            sym=sym,
            cmd=cmd,
            result=result,
            payment_id=pid,
            payment_before=before,
            payment_after=after,
            now=now,
            record_after=record,
            extra=extra,
        )
        self.steps.append(step)
        return step

    def run(self, trace: list[SymCmd]) -> list[Step]:
        for sym in trace:
            self.step(sym)
        return self.steps

    # ---------------------------------------------------------------- oracles

    def expected_release(self, step: Step) -> Invariant | None | str:
        """What `release` must answer, from the shadow model alone.

        Returns None for success, an Invariant for a refusal, or "error" when the payment
        does not exist. Mirrors the fixed check order documented in certs.verify:
        missing or other payment -> I1_NO_CERT; voided (mutate, cancel, sibling released)
        -> I2; consumed -> I3_REPLAY; expired -> I3_EXPIRED; nonce -> I1_NO_CERT;
        state -> I1_NOT_ELIGIBLE.
        """
        assert isinstance(step.cmd, Release)
        if step.payment_before is None:
            return "error"
        if step.state_before is State.DENIED:
            return Invariant.I6_DENIED
        info = self.cert_by_id.get(step.cmd.certificate_id)
        if info is None or info.payment_id != step.payment_id:
            return Invariant.I1_NO_CERT
        if info.id in step.extra["voided_before"] or info.epoch != step.extra["epoch_before"]:
            return Invariant.I2_FINGERPRINT
        if info.id in step.extra["released_before"]:
            return Invariant.I3_REPLAY
        if info.expires_at <= step.now:
            return Invariant.I3_EXPIRED
        if step.cmd.nonce != info.nonce:
            return Invariant.I1_NO_CERT
        if step.state_before is not State.ELIGIBLE_TO_SUBMIT:
            return Invariant.I1_NOT_ELIGIBLE
        return None
