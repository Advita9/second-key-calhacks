"""I7: hash-chained audit log detects edits to past records."""

from __future__ import annotations

import json

import pytest

from kernel.audit import GENESIS_HASH, AuditLog, chain_hash
from kernel.clock import FakeClock
from kernel.db import connect


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
