"""I7: hash-chained audit log detects edits to past records."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

import pytest

from kernel.audit import GENESIS_HASH, AuditChainError, AuditLog, chain_hash
from kernel.clock import FakeClock
from kernel.db import SCHEMA, Connection, connect, immediate


@pytest.fixture
def log(clock: FakeClock) -> AuditLog:
    return AuditLog(connect(":memory:"), clock)


def test_empty_log_verifies(log: AuditLog) -> None:
    r = log.verify()
    assert r.ok and r.length == 0 and r.first_bad_seq is None


def test_append_and_verify(log: AuditLog) -> None:
    for i in range(10):
        ev = log.append("tester", "PING", {"i": i})
        assert ev.seq == i + 1
    r = log.verify()
    assert r.ok and r.length == 10 and r.first_bad_seq is None


def test_chain_links(log: AuditLog) -> None:
    a = log.append("t", "A", {})
    b = log.append("t", "B", {})
    assert a.prev_hash == GENESIS_HASH
    assert b.prev_hash == a.hash
    assert b.hash == chain_hash(b.seq, b.ts, b.actor, b.kind, json.dumps({}), a.hash)


def test_tamper_detected_at_seq(log: AuditLog) -> None:
    for i in range(6):
        log.append("t", "K", {"amount": 100 + i})
    log.tamper(3, {"amount": 1})
    r = log.verify()
    assert not r.ok and r.first_bad_seq == 3 and r.length == 6


def test_relinking_later_row_still_detected(log: AuditLog, clock: FakeClock) -> None:
    for i in range(5):
        log.append("t", "K", {"n": i})
    conn = log.conn
    # Attacker edits row 2, recomputes its hash, and re-links row 3's prev_hash to the new hash.
    row = conn.execute("SELECT ts, actor, kind, prev_hash FROM audit WHERE seq=2").fetchone()
    payload = json.dumps({"n": 999}, sort_keys=True, separators=(",", ":"))
    new_hash = chain_hash(2, row[0], row[1], row[2], payload, row[3])
    conn.execute("UPDATE audit SET payload=?, hash=? WHERE seq=2", (payload, new_hash))
    conn.execute("UPDATE audit SET prev_hash=? WHERE seq=3", (new_hash,))
    r = log.verify()
    assert not r.ok and r.first_bad_seq == 3


def test_full_rewrite_detected_by_head_anchor(log: AuditLog) -> None:
    for i in range(4):
        log.append("t", "K", {"n": i})
    # Attacker rewrites every row consistently. The in-process head anchor still catches it.
    rows = log.conn.execute("SELECT seq, ts, actor, kind FROM audit ORDER BY seq").fetchall()
    prev = GENESIS_HASH
    for seq, ts, actor, kind in rows:
        payload = json.dumps({"n": -seq}, sort_keys=True, separators=(",", ":"))
        h = chain_hash(seq, ts, actor, kind, payload, prev)
        log.conn.execute(
            "UPDATE audit SET payload=?, prev_hash=?, hash=? WHERE seq=?", (payload, prev, h, seq)
        )
        prev = h
    r = log.verify()
    assert not r.ok and r.first_bad_seq == 4


def test_deleted_tail_detected(log: AuditLog) -> None:
    for i in range(3):
        log.append("t", "K", {"n": i})
    log.conn.execute("DELETE FROM audit WHERE seq=3")
    r = log.verify()
    assert not r.ok and r.first_bad_seq == 3


def test_tail_returns_latest_in_order(log: AuditLog) -> None:
    for i in range(5):
        log.append("t", "K", {"n": i})
    t = log.tail(2)
    assert [e.seq for e in t] == [4, 5]
    assert t[1].payload == {"n": 4}


def test_payload_with_datetime_is_canonical(log: AuditLog, clock: FakeClock) -> None:
    ev = log.append("t", "K", {"when": clock.now(), "b": 1, "a": 2})
    assert ev.payload == {"when": clock.now().isoformat(), "b": 1, "a": 2}
    assert log.verify().ok


def test_no_secrets_in_kind_or_actor_types(log: AuditLog) -> None:
    ev = log.append("bank_review:ops1", "CERT_ISSUED", {"certificate_id": "c1"})
    assert ev.kind == "CERT_ISSUED" and ev.actor == "bank_review:ops1"


def test_audit_verify_ok_after_rolled_back_in_txn_append(log: AuditLog) -> None:
    """The head advances only on commit: a rolled-back append must not leave verify red."""
    log.append("t", "K", {"n": 1})
    with pytest.raises(RuntimeError):
        with immediate(log.conn):
            log.append("t", "K", {"n": 2})
            log.append("t", "K", {"n": 3})
            raise RuntimeError("boom")
    r = log.verify()
    assert r.ok and r.length == 1
    ev = log.append("t", "K", {"n": 4})
    assert ev.seq == 2 and log.verify().ok and log.verify().length == 2


def test_joined_transaction_commit_advances_head(log: AuditLog) -> None:
    with immediate(log.conn):
        log.append("t", "A", {})
        log.append("t", "B", {})
    assert log.verify().ok and log.verify().length == 2


def test_append_refuses_when_tail_does_not_match_anchor(log: AuditLog) -> None:
    """A rewritten or truncated table cannot be silently extended."""
    for i in range(3):
        log.append("t", "K", {"n": i})
    log.conn.execute("DELETE FROM audit WHERE seq=3")
    with pytest.raises(AuditChainError):
        log.append("t", "K", {"n": 9})
    assert log.conn.execute("SELECT count(*) FROM audit").fetchone()[0] == 2
    assert not log.verify().ok


def test_tamper_does_not_block_later_appends(log: AuditLog) -> None:
    for i in range(3):
        log.append("t", "K", {"n": i})
    log.tamper(2, {"n": 99})
    log.append("t", "K", {"n": 3})  # chain tail unchanged, append still allowed
    r = log.verify()
    assert not r.ok and r.first_bad_seq == 2


def test_concurrent_appends_without_kernel_lock_lose_nothing(clock: FakeClock) -> None:
    """immediate() locks the connection itself, so callers cannot interleave transactions."""
    log = AuditLog(connect(":memory:"), clock)
    n_threads, per_thread = 8, 25
    barrier = threading.Barrier(n_threads)

    def go(i: int) -> None:
        barrier.wait()
        for j in range(per_thread):
            log.append(f"t{i}", "K", {"i": i, "j": j})

    threads = [threading.Thread(target=go, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    r = log.verify()
    assert r.ok and r.length == n_threads * per_thread


def test_deleted_middle_row_reports_the_gap_seq(log: AuditLog) -> None:
    for i in range(4):
        log.append("t", "K", {"n": i})
    log.conn.execute("DELETE FROM audit WHERE seq=2")
    r = log.verify()
    assert not r.ok and r.first_bad_seq == 2 and r.length == 3


class _CommitFails(Connection):
    """A connection whose COMMIT raises once, to exercise the rollback path in immediate()."""

    fail_next_commit = False

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
        if sql == "COMMIT" and self.fail_next_commit:
            self.fail_next_commit = False
            raise sqlite3.OperationalError("disk I/O error (simulated)")
        return super().execute(sql, parameters)


def test_commit_failure_rolls_back_head(clock: FakeClock) -> None:
    conn = sqlite3.connect(":memory:", isolation_level=None, factory=_CommitFails)
    conn.executescript(SCHEMA)
    log = AuditLog(conn, clock)
    log.append("t", "K", {"n": 1})
    conn.fail_next_commit = True
    with pytest.raises(sqlite3.OperationalError):
        log.append("t", "K", {"n": 2})
    assert not conn.in_transaction
    assert conn.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
    r = log.verify()
    assert r.ok and r.length == 1
    ev = log.append("t", "K", {"n": 3})
    assert ev.seq == 2 and log.verify().ok
