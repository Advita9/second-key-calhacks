"""RoomStore: same limits and the same stripping rules as the SpacetimeDB module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kernel.audit import AuditLog
from kernel.clock import FakeClock
from kernel.db import connect
from kernel.room_memory import MAX_TURN_CHARS, RoomError, RoomStore

T0 = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)


def make_room(store: RoomStore, code: str = "DEMO") -> str:
    store.create_room(code, T0)
    store.set_room_status(code, "live")
    return code


def test_turn_length_limit() -> None:
    store = RoomStore()
    room = make_room(store)
    p = store.join(room, "alice", T0)
    store.submit_turn(room, p.identity, "x" * MAX_TURN_CHARS, T0)
    with pytest.raises(RoomError) as ei:
        store.submit_turn(room, p.identity, "x" * (MAX_TURN_CHARS + 1), T0.replace(minute=1))
    assert ei.value.code == "TOO_LONG"


def test_rate_limit_one_turn_per_3s(clock: FakeClock) -> None:
    store = RoomStore()
    room = make_room(store)
    p = store.join(room, "alice", clock.now())
    store.submit_turn(room, p.identity, "first", clock.now())
    clock.advance(2.9)
    with pytest.raises(RoomError) as ei:
        store.submit_turn(room, p.identity, "too soon", clock.now())
    assert ei.value.code == "RATE_LIMIT"
    clock.advance(0.2)
    store.submit_turn(room, p.identity, "ok now", clock.now())
    # Another player is not affected by alice's limit.
    q = store.join(room, "bob", clock.now())
    store.submit_turn(room, q.identity, "bob first", clock.now())


def test_closed_room_rejects_join_and_turn() -> None:
    store = RoomStore()
    room = make_room(store)
    p = store.join(room, "alice", T0)
    store.set_room_status(room, "debrief")
    with pytest.raises(RoomError) as ei:
        store.submit_turn(room, p.identity, "hi", T0)
    assert ei.value.code == "CLOSED"
    with pytest.raises(RoomError):
        store.join(room, "carol", T0)


def test_only_attackers_submit() -> None:
    store = RoomStore()
    store.create_room("DEMO", T0, operator="op-identity")
    with pytest.raises(RoomError) as ei:
        store.submit_turn("DEMO", "op-identity", "hi", T0)
    assert ei.value.code == "NOT_ATTACKER"
    with pytest.raises(RoomError):
        store.submit_turn("DEMO", "stranger", "hi", T0)


def test_handle_filter() -> None:
    store = RoomStore()
    room = make_room(store)
    for bad in ["", "a" * 25, "<script>", "fuckface", "my ssn 123"]:
        with pytest.raises(RoomError) as ei:
            store.join(room, bad, T0)
        assert ei.value.code == "BAD_HANDLE"
    assert store.join(room, " Red Team-1 ", T0).handle == "Red Team-1"


def test_record_outcome_updates_leaderboard_and_scoreboard() -> None:
    store = RoomStore()
    room = make_room(store)
    p = store.join(room, "alice", T0)
    t1 = store.submit_turn(room, p.identity, "one", T0)
    store.record_outcome(t1.id, 40, "", "NONE", [], "", T0)
    t2 = store.submit_turn(room, p.identity, "two", T0.replace(minute=1))
    store.record_outcome(t2.id, 10, "", "HOLD", ["H-01"], "", T0)
    lb = store.leaderboard[p.identity]
    assert lb.best_stage == 40 and lb.attempts == 2 and lb.handle == "alice"
    sb = store.scoreboard[room]
    assert sb.attempts == 2 and sb.unauthorized_releases == 0
    assert store.turns[t1.id].status == "done"
    # Stage 100 is the headline failure counter.
    t3 = store.submit_turn(room, p.identity, "three", T0.replace(minute=2))
    store.record_outcome(t3.id, 100, "pay-1", "ALLOW", ["A-01"], "", T0)
    assert store.scoreboard[room].unauthorized_releases == 1
    assert store.leaderboard[p.identity].best_stage == 100
    store.record_legit_completed(room)
    assert store.scoreboard[room].legit_completed == 1


def test_record_outcome_idempotent_per_turn() -> None:
    store = RoomStore()
    room = make_room(store)
    p = store.join(room, "alice", T0)
    t = store.submit_turn(room, p.identity, "one", T0)
    first = store.record_outcome(t.id, 10, "", "HOLD", ["H-01"], "", T0)
    second = store.record_outcome(t.id, 100, "", "ALLOW", [], "", T0)
    assert first == second
    assert store.scoreboard[room].attempts == 1
    assert store.scoreboard[room].unauthorized_releases == 0


def test_record_outcome_validates_stage_and_decision() -> None:
    store = RoomStore()
    room = make_room(store)
    p = store.join(room, "alice", T0)
    t = store.submit_turn(room, p.identity, "one", T0)
    with pytest.raises(RoomError):
        store.record_outcome(t.id, 55, "", "HOLD", [], "", T0)
    with pytest.raises(RoomError):
        store.record_outcome(t.id, 10, "", "MAYBE", [], "", T0)


def test_attacker_snapshot_strips_rule_ids_refusal_and_others() -> None:
    store = RoomStore()
    room = make_room(store)
    alice = store.join(room, "alice", T0)
    bob = store.join(room, "bob", T0)
    ta = store.submit_turn(room, alice.identity, "alice turn", T0)
    tb = store.submit_turn(room, bob.identity, "bob turn", T0)
    store.record_reply(ta.id, "no dear", "", False, T0)
    store.record_reply(tb.id, "no dear", "", False, T0)
    store.record_outcome(ta.id, 10, "", "HOLD", ["H-01", "H-02"], "SETTLEMENT REFUSED", T0)
    store.record_outcome(tb.id, 40, "", "HOLD", ["H-03"], "", T0)
    store.mirror_audit(room, 1, "payment.created", "h1", "0" * 64, "ts")

    snap = store.snapshot(room, "attacker", alice.identity)
    dumped = snap.model_dump(by_alias=True, mode="json")
    text = str(dumped)
    assert "ruleIds" not in text and "rule_ids" not in text
    assert "H-01" not in text and "SETTLEMENT REFUSED" not in text and "refusal" not in text
    assert dumped["outcomes"] == []
    assert [o["turnId"] for o in dumped["myOutcomes"]] == [ta.id]
    assert set(dumped["myOutcomes"][0]) == {"turnId", "stage", "decision"}
    assert [t["id"] for t in dumped["turns"]] == [ta.id]
    assert [r["turnId"] for r in dumped["replies"]] == [ta.id]
    assert dumped["audit"] == []
    # Leaderboard and scoreboard are shared.
    assert {lb["handle"] for lb in dumped["leaderboard"]} == {"alice", "bob"}
    assert dumped["scoreboard"]["attempts"] == 2

    board = store.snapshot(room, "board", None).model_dump(by_alias=True, mode="json")
    assert len(board["outcomes"]) == 2 and board["outcomes"][0]["ruleIds"] == ["H-01", "H-02"]
    assert board["audit"] == []
    ops = store.snapshot(room, "ops", None).model_dump(by_alias=True, mode="json")
    assert [a["seq"] for a in ops["audit"]] == [1]


def test_mirror_audit_matches_kernel_chain(clock: FakeClock) -> None:
    conn = connect(":memory:")
    audit = AuditLog(conn, clock)
    e1 = audit.append("kernel", "payment.created", {"id": "p1"})
    e2 = audit.append("kernel", "payment.held", {"id": "p1"})
    store = RoomStore()
    room = make_room(store)
    for ev in audit.tail(50):
        store.mirror_audit(room, ev.seq, ev.kind, ev.hash, ev.prev_hash, ev.ts)
    # Idempotent on seq.
    store.mirror_audit(room, e1.seq, "x", "y", "z", "w")
    rows = store.snapshot(room, "ops", None).audit
    assert [(r.seq, r.hash, r.prev_hash) for r in rows] == [
        (e1.seq, e1.hash, e1.prev_hash),
        (e2.seq, e2.hash, e2.prev_hash),
    ]
    assert rows[1].prev_hash == rows[0].hash
    assert audit.verify().ok


def test_reset_room_clears_room_only() -> None:
    store = RoomStore()
    a = make_room(store, "AAA")
    b = make_room(store, "BBB")
    pa = store.join(a, "alice", T0)
    pb = store.join(b, "bob", T0)
    ta = store.submit_turn(a, pa.identity, "x", T0)
    tb = store.submit_turn(b, pb.identity, "y", T0)
    store.record_outcome(ta.id, 100, "", "ALLOW", [], "", T0)
    store.record_outcome(tb.id, 100, "", "ALLOW", [], "", T0)
    store.reset_room(a)
    sa = store.snapshot(a, "ops", None)
    sb = store.snapshot(b, "ops", None)
    assert sa.turns == [] and sa.outcomes == [] and sa.leaderboard == []
    assert sa.scoreboard is not None and sa.scoreboard.unauthorized_releases == 0
    assert len(sb.turns) == 1 and sb.scoreboard is not None
    assert sb.scoreboard.unauthorized_releases == 1
