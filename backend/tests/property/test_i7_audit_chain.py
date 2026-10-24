"""I7: the audit log is hash-chained. After any trace it verifies; after any single edit of
a past row it does not, and the reported seq is at or before the edited row.

Deleting a middle row is detected too, but the kernel currently reports the seq of the row
after the gap (see test_found_i7_delete_reports_next_seq.py), so that location claim lives
in the regression test rather than here."""

from __future__ import annotations

import json
import sqlite3

from hypothesis import event, given, settings
from hypothesis import strategies as st

from tests.property.driver import Driver
from tests.property.strategies import SymCmd, make_kernel, traces

EDITS: tuple[str, ...] = ("payload", "kind", "actor", "ts", "prev_hash", "hash")
FAKE_HASH = "f" * 64
COLS = "ts, actor, kind, payload, prev_hash, hash"


def edit_row(conn: sqlite3.Connection, seq: int, what: str) -> None:
    if what == "payload":
        (raw,) = conn.execute("SELECT payload FROM audit WHERE seq=?", (seq,)).fetchone()
        doc = json.loads(raw)
        doc["tampered"] = True
        conn.execute("UPDATE audit SET payload=? WHERE seq=?", (json.dumps(doc), seq))
    elif what == "kind":
        conn.execute("UPDATE audit SET kind = kind || '_X' WHERE seq=?", (seq,))
    elif what == "actor":
        conn.execute("UPDATE audit SET actor = actor || '_x' WHERE seq=?", (seq,))
    elif what == "ts":
        conn.execute("UPDATE audit SET ts = ts || 'Z' WHERE seq=?", (seq,))
    elif what == "prev_hash":
        conn.execute("UPDATE audit SET prev_hash=? WHERE seq=?", (FAKE_HASH, seq))
    elif what == "hash":
        conn.execute("UPDATE audit SET hash=? WHERE seq=?", (FAKE_HASH, seq))
    else:
        raise ValueError(what)


def swap_rows(conn: sqlite3.Connection, a: int, b: int) -> None:
    ra = conn.execute(f"SELECT {COLS} FROM audit WHERE seq=?", (a,)).fetchone()
    rb = conn.execute(f"SELECT {COLS} FROM audit WHERE seq=?", (b,)).fetchone()
    sql = "UPDATE audit SET ts=?, actor=?, kind=?, payload=?, prev_hash=?, hash=? WHERE seq=?"
    conn.execute(sql, (*rb, a))
    conn.execute(sql, (*ra, b))


def length(conn: sqlite3.Connection) -> int:
    (n,) = conn.execute("SELECT COUNT(*) FROM audit").fetchone()
    return int(n)


@settings(deadline=None)
@given(traces())
def test_chain_verifies_after_any_trace(trace: list[SymCmd]) -> None:
    kernel, clock = make_kernel()
    Driver(kernel, clock).run(trace)
    r = kernel.audit_verify()
    assert r.ok and r.first_bad_seq is None
    assert r.length == length(kernel.conn) >= 1
    seqs = [row[0] for row in kernel.conn.execute("SELECT seq FROM audit ORDER BY seq")]
    assert seqs == list(range(1, r.length + 1))


@settings(deadline=None)
@given(traces(max_ops=8), st.data())
def test_editing_any_single_past_row_is_detected_at_or_before_it(
    trace: list[SymCmd], data: st.DataObject
) -> None:
    kernel, clock = make_kernel()
    Driver(kernel, clock).run(trace)
    n = length(kernel.conn)
    seq = data.draw(st.integers(min_value=1, max_value=n), label="seq")
    what = data.draw(st.sampled_from(EDITS), label="edit")
    event(f"edit={what}")
    edit_row(kernel.conn, seq, what)
    r = kernel.audit_verify()
    assert not r.ok
    assert r.first_bad_seq is not None
    assert r.first_bad_seq <= seq
    assert r.length == n


@settings(deadline=None)
@given(traces(max_ops=8), st.data())
def test_swapping_two_rows_is_detected_at_or_before_the_earlier_one(
    trace: list[SymCmd], data: st.DataObject
) -> None:
    kernel, clock = make_kernel()
    Driver(kernel, clock).run(trace)
    n = length(kernel.conn)
    a = data.draw(st.integers(min_value=1, max_value=n), label="a")
    b = data.draw(st.integers(min_value=1, max_value=n).filter(lambda x: x != a), label="b")
    swap_rows(kernel.conn, a, b)
    r = kernel.audit_verify()
    assert not r.ok
    assert r.first_bad_seq is not None
    assert r.first_bad_seq <= min(a, b)


@settings(deadline=None)
@given(traces(max_ops=8), st.data())
def test_deleting_any_row_is_detected(trace: list[SymCmd], data: st.DataObject) -> None:
    kernel, clock = make_kernel()
    Driver(kernel, clock).run(trace)
    n = length(kernel.conn)
    seq = data.draw(st.integers(min_value=1, max_value=n), label="seq")
    event("tail" if seq == n else "middle")
    kernel.conn.execute("DELETE FROM audit WHERE seq=?", (seq,))
    r = kernel.audit_verify()
    assert not r.ok
    assert r.first_bad_seq is not None
    assert r.length == n - 1
    if seq == n:
        assert r.first_bad_seq == seq


@settings(deadline=None)
@given(traces(max_ops=8), st.data())
def test_rehashing_the_edited_row_does_not_hide_the_edit(
    trace: list[SymCmd], data: st.DataObject
) -> None:
    """An attacker who recomputes the edited row's own hash still breaks the next link,
    and on the last row still disagrees with the in-process head."""
    from kernel.audit import chain_hash

    kernel, clock = make_kernel()
    Driver(kernel, clock).run(trace)
    n = length(kernel.conn)
    seq = data.draw(st.integers(min_value=1, max_value=n), label="seq")
    edit_row(kernel.conn, seq, "payload")
    row = kernel.conn.execute(
        "SELECT ts, actor, kind, payload, prev_hash FROM audit WHERE seq=?", (seq,)
    ).fetchone()
    kernel.conn.execute("UPDATE audit SET hash=? WHERE seq=?", (chain_hash(seq, *row), seq))
    r = kernel.audit_verify()
    assert not r.ok
    assert r.first_bad_seq is not None
    assert seq <= r.first_bad_seq <= seq + 1
