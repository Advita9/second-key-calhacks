"""Hash-chained audit log (I7). Each row hashes its content plus the previous row's hash.

The log keeps an anchor (seq, hash) of the last row it committed, in process and, for file
databases, in a sidecar `<db>.head.json` written atomically on every commit. `append` refuses
to extend a chain whose tail does not match the anchor, and the anchor only moves when the
enclosing transaction commits, so a rolled-back append never leaves `verify()` red. On startup
the sidecar is compared to the table: a shorter or different tail (rows erased or rewritten
while the kernel was down) makes `verify()` red and blocks `append` until an operator calls
`acknowledge_anchor`, which is itself audited.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

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


AnchorStatus = Literal["ok", "mismatch", "none"]


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    length: int
    first_bad_seq: int | None = None
    anchor: AnchorStatus = "none"


def anchor_path_for(db_path: str) -> Path | None:
    """Sidecar next to the database; none for `:memory:` (in-process anchor only)."""
    if db_path == ":memory:" or db_path.startswith("file:") and "mode=memory" in db_path:
        return None
    return Path(f"{db_path}.head.json")


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

    def __init__(self, conn: Connection, clock: Clock, *, anchor_path: Path | None = None) -> None:
        self.conn = conn
        self._clock = clock
        self._anchor_path = anchor_path
        row = conn.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        self._head_seq: int = row[0] if row else 0
        self._head: str = row[1] if row else GENESIS_HASH
        self._pending: tuple[int, str] | None = None
        # Durable anchor from the sidecar, compared against the table on every verify.
        self._anchor: tuple[int, str] | None = self._load_anchor()
        self._anchor_mismatch: int | None = self._check_anchor()
        if self._anchor_mismatch is not None:
            log.critical(
                "audit.anchor_mismatch",
                extra={"first_bad_seq": self._anchor_mismatch, "table_seq": self._head_seq},
            )
        conn.commit_hooks.append(self._on_commit)
        conn.rollback_hooks.append(self._on_rollback)

    # ------------------------------------------------------------------ sidecar anchor

    def _load_anchor(self) -> tuple[int, str] | None:
        if self._anchor_path is None or not self._anchor_path.is_file():
            return None
        try:
            raw = json.loads(self._anchor_path.read_text("utf-8"))
            seq, h = int(raw["seq"]), str(raw["hash"])
        except (OSError, ValueError, KeyError, TypeError):
            log.error("audit.anchor_unreadable", extra={"path": str(self._anchor_path)})
            return (0, "")  # unreadable sidecar counts as a mismatch, never as absence
        return (seq, h)

    def _write_anchor(self, seq: int, h: str) -> None:
        if self._anchor_path is None:
            return
        doc = {"seq": seq, "hash": h, "updated_at": self._clock.now().isoformat()}
        path = self._anchor_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(doc, sort_keys=True))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._anchor = (seq, h)

    def _check_anchor(self) -> int | None:
        """Seq of the first row the table disagrees with the sidecar on, or None when fine."""
        if self._anchor_path is None:
            return None
        rows = self.conn.execute("SELECT seq, hash FROM audit ORDER BY seq").fetchall()
        if self._anchor is None:
            # File database with history but no sidecar: the anchor itself was erased.
            return 1 if rows else None
        seq, h = self._anchor
        if seq == 0 and h == "":
            return 1  # unreadable sidecar
        if len(rows) < seq:
            return len(rows) + 1
        if seq == 0:
            return None
        row = rows[seq - 1]
        if row[0] != seq or row[1] != h:
            return seq
        return None

    def anchor_status(self) -> AnchorStatus:
        if self._anchor_path is None:
            return "none"
        if self._anchor_mismatch is not None:
            return "mismatch"
        return "ok" if self._anchor is not None else "none"

    def acknowledge_anchor(self, actor: str) -> AuditEvent:
        """Operator accepts the current table as the new baseline after a mismatch. Audited,
        and the sidecar is rewritten to the new tail by the commit hook."""
        previous = self._anchor
        self._anchor_mismatch = None
        row = self.conn.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        self._head_seq, self._head = (row[0], row[1]) if row else (0, GENESIS_HASH)
        self._pending = None
        table_seq = self._head_seq
        ev = self.append(
            actor,
            "AUDIT_ANCHOR_ACKNOWLEDGED",
            {
                "previous_anchor_seq": previous[0] if previous else None,
                "previous_anchor_hash": previous[1] if previous else None,
                "table_seq": table_seq,
            },
        )
        log.warning("audit.anchor_acknowledged", extra={"actor": actor, "seq": ev.seq})
        return ev

    # The head only advances on commit. Inside a transaction, `_pending` is the tail we
    # expect to see; a rollback discards it.
    def _on_commit(self) -> None:
        if self._pending is not None:
            self._head_seq, self._head = self._pending
            self._pending = None
            self._write_anchor(self._head_seq, self._head)

    def _on_rollback(self) -> None:
        self._pending = None

    def _expected_tail(self) -> tuple[int, str]:
        return self._pending if self._pending is not None else (self._head_seq, self._head)

    def append(self, actor: str, kind: str, payload: Mapping[str, object]) -> AuditEvent:
        if self._anchor_mismatch is not None:
            raise AuditChainError(
                "audit anchor mismatch: history was altered while the kernel was down; "
                "an operator must acknowledge before new rows can be written"
            )
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
        with self.conn.lock:
            rows = self.conn.execute(
                "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit ORDER BY seq"
            ).fetchall()
            head_seq, head = self._expected_tail()
            anchor = self.anchor_status()
        if anchor == "mismatch":
            assert self._anchor_mismatch is not None
            return VerifyResult(
                ok=False, length=len(rows), first_bad_seq=self._anchor_mismatch, anchor=anchor
            )
        prev = GENESIS_HASH
        expected_seq = 1
        for seq, ts, actor, kind, payload_json, prev_hash, h in rows:
            if seq != expected_seq:
                # A gap: name the missing row, not the one after it.
                return VerifyResult(
                    ok=False, length=len(rows), first_bad_seq=expected_seq, anchor=anchor
                )
            if prev_hash != prev:
                return VerifyResult(ok=False, length=len(rows), first_bad_seq=seq, anchor=anchor)
            if chain_hash(seq, ts, actor, kind, payload_json, prev_hash) != h:
                return VerifyResult(ok=False, length=len(rows), first_bad_seq=seq, anchor=anchor)
            prev = h
            expected_seq += 1
        if len(rows) < head_seq:
            # Tail rows were deleted. The first missing seq is the bad one.
            return VerifyResult(
                ok=False, length=len(rows), first_bad_seq=len(rows) + 1, anchor=anchor
            )
        if prev != head:
            # Chain is internally consistent but does not end where this process left it:
            # rows were rewritten wholesale. Blame the head row.
            return VerifyResult(
                ok=False, length=len(rows), first_bad_seq=max(len(rows), 1), anchor=anchor
            )
        return VerifyResult(ok=True, length=len(rows), first_bad_seq=None, anchor=anchor)

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
        with self.conn.lock:
            rows = self.conn.execute(
                "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit "
                "ORDER BY seq DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_event(r) for r in reversed(rows)]

    def for_payment(self, payment_id: str) -> list[AuditEvent]:
        with self.conn.lock:
            rows = self.conn.execute(
                "SELECT seq, ts, actor, kind, payload, prev_hash, hash FROM audit "
                "WHERE json_extract(payload, '$.payment_id') = ? ORDER BY seq",
                (payment_id,),
            ).fetchall()
        return [_event(r) for r in rows]

    def payment_ids_with_kind(self, kinds: tuple[str, ...]) -> set[str]:
        """Payments that have at least one audit row of any of `kinds` (startup rebuilds)."""
        marks = ",".join("?" for _ in kinds)
        with self.conn.lock:
            rows = self.conn.execute(
                "SELECT DISTINCT json_extract(payload, '$.payment_id') FROM audit "
                f"WHERE kind IN ({marks})",
                kinds,
            ).fetchall()
        return {str(r[0]) for r in rows if r[0] is not None}
