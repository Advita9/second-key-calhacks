"""SQLite plumbing: schema, connection, explicit write transactions, payment rows.

Writes go through `immediate()`, which takes the connection's own RLock before BEGIN
IMMEDIATE, so two threads can never interleave inside one SQLite transaction even if a
caller forgets the Kernel lock. Commit and rollback hooks let the audit log advance its
head only when the transaction actually commits.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

from kernel.models import Beneficiary, Payment, Rail, State

SCHEMA = """
CREATE TABLE IF NOT EXISTS payment (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    beneficiary_name TEXT NOT NULL,
    beneficiary_account_ref TEXT NOT NULL,
    beneficiary_is_new INTEGER NOT NULL,
    rail TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    state TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    nessie_transfer_id TEXT
);
CREATE TABLE IF NOT EXISTS attestation (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES payment(id),
    actor_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    voided_at TEXT
);
CREATE TABLE IF NOT EXISTS certificate (
    id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL REFERENCES payment(id),
    fingerprint TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    nonce TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    voided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attestation_payment ON attestation(payment_id);
CREATE INDEX IF NOT EXISTS certificate_payment ON certificate(payment_id);
"""


class Connection(sqlite3.Connection):
    """sqlite3 connection with its own reentrant lock and transaction hooks."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.lock = threading.RLock()
        self.commit_hooks: list[Callable[[], None]] = []
        self.rollback_hooks: list[Callable[[], None]] = []


def connect(path: str = ":memory:") -> Connection:
    """Open a connection in manual-transaction mode and apply the schema once.

    `isolation_level=None` disables sqlite3's implicit BEGIN so `immediate()` owns every
    write transaction. `check_same_thread=False` because `immediate()` serialises writers
    with the connection lock; never open a second connection to `:memory:`.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False, factory=Connection)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=MEMORY" if path == ":memory:" else "PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def immediate(conn: Connection) -> Iterator[Connection]:
    """BEGIN IMMEDIATE write transaction under the connection lock.

    Joins an already-open transaction (same thread, lock is reentrant) instead of nesting.
    Hooks fire only when the outermost transaction commits or rolls back.
    """
    with conn.lock:
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            for hook in conn.rollback_hooks:
                hook()
            raise
        conn.execute("COMMIT")
        for hook in conn.commit_hooks:
            hook()


def insert_payment(conn: Connection, p: Payment) -> None:
    """Insert a new payment. Only DRAFT rows can be born; every later state is a transition."""
    if p.state is not State.DRAFT or p.nessie_transfer_id is not None:
        raise ValueError("insert_payment: new payments must be DRAFT with no transfer id")
    with immediate(conn):
        conn.execute(
            """INSERT INTO payment (id, account_id, amount_cents, currency, beneficiary_name,
               beneficiary_account_ref, beneficiary_is_new, rail, conversation_id, state,
               fingerprint, policy_version, created_at, nessie_transfer_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
            (
                p.id,
                p.account_id,
                p.amount_cents,
                p.currency,
                p.beneficiary.name,
                p.beneficiary.account_ref,
                int(p.beneficiary.is_new),
                p.rail.value,
                p.conversation_id,
                State.DRAFT.value,
                p.fingerprint,
                p.policy_version,
                p.created_at.isoformat(),
            ),
        )


def load_payment(conn: sqlite3.Connection, payment_id: str) -> Payment:
    row = conn.execute(
        """SELECT id, account_id, amount_cents, currency, beneficiary_name,
                  beneficiary_account_ref, beneficiary_is_new, rail, conversation_id, state,
                  fingerprint, policy_version, created_at, nessie_transfer_id
           FROM payment WHERE id=?""",
        (payment_id,),
    ).fetchone()
    if row is None:
        raise KeyError(payment_id)
    return Payment(
        id=row[0],
        account_id=row[1],
        amount_cents=row[2],
        currency=row[3],
        beneficiary=Beneficiary(name=row[4], account_ref=row[5], is_new=bool(row[6])),
        rail=Rail(row[7]),
        conversation_id=row[8],
        state=State(row[9]),
        fingerprint=row[10],
        policy_version=row[11],
        created_at=datetime.fromisoformat(row[12]),
        nessie_transfer_id=row[13],
    )
