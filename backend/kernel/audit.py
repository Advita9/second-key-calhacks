"""Hash-chained audit log (I7). Each row hashes its content plus the previous row's hash.

The log keeps an in-process anchor (seq, hash) of the last row it committed. `append`
refuses to extend a chain whose tail does not match the anchor, and the anchor only moves
when the enclosing transaction commits, so a rolled-back append never leaves `verify()` red.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from kernel.clock import Clock
from kernel.db import Connection, immediate
from kernel.fingerprint import canonical_json

log = logging.getLogger("second_key.audit")

GENESIS_HASH = "0" * 64


class AuditChainError(RuntimeError):
    """The table tail no longer matches what this process last wrote. Refuse to append."""


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    seq: int
    ts: str
    actor: str
    kind: str
    payload: dict[str, object]
    prev_hash: str
    hash: str


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    length: int
    first_bad_seq: int | None = None


def chain_hash(seq: int, ts: str, actor: str, kind: str, payload_json: str, prev_hash: str) -> str:
    """Hash of one row. The payload is hashed as the exact JSON string stored in the row."""
    material = json.dumps([seq, ts, actor, kind, payload_json, prev_hash], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _event(r: tuple[object, ...]) -> AuditEvent:
    return AuditEvent(
        seq=int(str(r[0])),
        ts=str(r[1]),
        actor=str(r[2]),
        kind=str(r[3]),
        payload=json.loads(str(r[4])),
        prev_hash=str(r[5]),
        hash=str(r[6]),
    )


class AuditLog:
    """Append-only log. `verify()` recomputes the whole chain; `tamper()` exists for the demo."""

    def __init__(self, conn: Connection, clock: Clock) -> None:
        self.conn = conn
        self._clock = clock
        row = conn.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        self._head_seq: int = row[0] if row else 0
        self._head: str = row[1] if row else GENESIS_HASH
        self._pending: tuple[int, str] | None = None
        conn.commit_hooks.append(self._on_commit)
        conn.rollback_hooks.append(self._on_rollback)

    # The head only advances on commit. Inside a transaction, `_pending` is the tail we
    # expect to see; a rollback discards it.
    def _on_commit(self) -> None:
        if self._pending is not None:
            self._head_seq, self._head = self._pending
            self._pending = None

    def _on_rollback(self) -> None:
        self._pending = None

    def _expected_tail(self) -> tuple[int, str]:
        return self._pending if self._pending is not None else (self._head_seq, self._head)

    def append(self, actor: str, kind: str, payload: Mapping[str, object]) -> AuditEvent:
        payload_json = canonical_json(dict(payload))
        ts = self._clock.now().isoformat()
        with immediate(self.conn):
            last = self.conn.execute(
                "SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            tail = (last[0], last[1]) if last else (0, GENESIS_HASH)
            if tail != self._expected_tail():
                raise AuditChainError(
                    f"audit tail {tail[0]} does not match anchor {self._expected_tail()[0]}"
                )
            seq = tail[0] + 1
            prev_hash = tail[1]
            h = chain_hash(seq, ts, actor, kind, payload_json, prev_hash)
            self.conn.execute(
                "INSERT INTO audit (seq, ts, actor, kind, payload, prev_hash, hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (seq, ts, actor, kind, payload_json, prev_hash, h),
            )
            self._pending = (seq, h)
        log.info("audit.append", extra={"seq": seq, "kind": kind, "actor": actor})
        return AuditEvent(
            seq=seq,
            ts=ts,
            actor=actor,
            kind=kind,
            payload=json.loads(payload_json),
            prev_hash=prev_hash,
            hash=h,
        )

    def verify(self) -> VerifyResult:
        rows = self.conn.execute(
            "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit ORDER BY seq"
        ).fetchall()
        prev = GENESIS_HASH
        expected_seq = 1
        for seq, ts, actor, kind, payload_json, prev_hash, h in rows:
            if seq != expected_seq or prev_hash != prev:
                return VerifyResult(ok=False, length=len(rows), first_bad_seq=seq)
            if chain_hash(seq, ts, actor, kind, payload_json, prev_hash) != h:
                return VerifyResult(ok=False, length=len(rows), first_bad_seq=seq)
            prev = h
            expected_seq += 1
        head_seq, head = self._expected_tail()
        if len(rows) < head_seq:
            # Tail rows were deleted. The first missing seq is the bad one.
            return VerifyResult(ok=False, length=len(rows), first_bad_seq=len(rows) + 1)
        if prev != head:
            # Chain is internally consistent but does not end where this process left it:
            # rows were rewritten wholesale. Blame the head row.
            return VerifyResult(ok=False, length=len(rows), first_bad_seq=max(len(rows), 1))
        return VerifyResult(ok=True, length=len(rows), first_bad_seq=None)

    def tamper(self, seq: int, patch: Mapping[str, object]) -> None:
        """DEMO ONLY: edit a past payload in place without re-hashing, so verify() goes red."""
        row = self.conn.execute("SELECT payload FROM audit WHERE seq=?", (seq,)).fetchone()
        if row is None:
            raise KeyError(seq)
        payload = json.loads(row[0])
        payload.update(patch)
        with immediate(self.conn):
            self.conn.execute(
                "UPDATE audit SET payload=? WHERE seq=?", (canonical_json(payload), seq)
            )
        log.warning("audit.tamper", extra={"seq": seq})

    def tail(self, limit: int = 200) -> list[AuditEvent]:
        rows = self.conn.execute(
            "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit "
            "ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_event(r) for r in reversed(rows)]

    def for_payment(self, payment_id: str) -> list[AuditEvent]:
        rows = self.conn.execute(
            "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit "
            "WHERE json_extract(payload, '$.payment_id') = ? ORDER BY seq",
            (payment_id,),
        ).fetchall()
        return [_event(r) for r in rows]
