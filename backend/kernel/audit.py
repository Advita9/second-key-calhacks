"""Hash-chained audit log (I7). Each row hashes its content plus the previous row's hash."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from kernel.clock import Clock
from kernel.db import immediate
from kernel.fingerprint import canonical_json

log = logging.getLogger("second_key.audit")

GENESIS_HASH = "0" * 64


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


class AuditLog:
    """Append-only log. `verify()` recomputes the whole chain; `tamper()` exists for the demo."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self.conn = conn
        self._clock = clock
        row = conn.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        # In-process anchor of the last row we wrote. Catches a consistent full rewrite or a
        # truncation of the table within this process; an external anchor would extend that.
        self._head_seq: int = row[0] if row else 0
        self._head: str = row[1] if row else GENESIS_HASH

    def append(self, actor: str, kind: str, payload: Mapping[str, object]) -> AuditEvent:
        payload_json = canonical_json(dict(payload))
        ts = self._clock.now().isoformat()
        with immediate(self.conn):
            last = self.conn.execute(
                "SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq = (last[0] + 1) if last else 1
            prev_hash = last[1] if last else GENESIS_HASH
            h = chain_hash(seq, ts, actor, kind, payload_json, prev_hash)
            self.conn.execute(
                "INSERT INTO audit (seq, ts, actor, kind, payload, prev_hash, hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (seq, ts, actor, kind, payload_json, prev_hash, h),
            )
        self._head = h
        self._head_seq = seq
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
        if len(rows) < self._head_seq:
            # Tail rows were deleted. The first missing seq is the bad one.
            return VerifyResult(ok=False, length=len(rows), first_bad_seq=len(rows) + 1)
        if prev != self._head:
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
        return [
            AuditEvent(
                seq=r[0],
                ts=r[1],
                actor=r[2],
                kind=r[3],
                payload=json.loads(r[4]),
                prev_hash=r[5],
                hash=r[6],
            )
            for r in reversed(rows)
        ]
