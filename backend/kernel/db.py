"""SQLite plumbing: schema, connection, explicit write transactions, payment rows."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
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


def connect(path: str = ":memory:") -> sqlite3.Connection:
    """Open a connection in manual-transaction mode and apply the schema once.

    `isolation_level=None` disables sqlite3's implicit BEGIN so `immediate()` owns
    every write transaction. `check_same_thread=False` because the Kernel facade
    serialises access with its own lock; never open a second connection to `:memory:`.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=MEMORY" if path == ":memory:" else "PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def immediate(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE write transaction. Joins an already-open transaction instead of nesting."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def insert_payment(conn: sqlite3.Connection, p: Payment) -> None:
    with immediate(conn):
        conn.execute(
            """INSERT INTO payment (id, account_id, amount_cents, currency, beneficiary_name,
               beneficiary_account_ref, beneficiary_is_new, rail, conversation_id, state,
               fingerprint, policy_version, created_at, nessie_transfer_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                p.state.value,
                p.fingerprint,
                p.policy_version,
                p.created_at.isoformat(),
                p.nessie_transfer_id,
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


def update_payment_fields(conn: sqlite3.Connection, p: Payment) -> None:
    """Rewrite the money-moving fields of a payment row. Never touches state; see state.py."""
    with immediate(conn):
        cur = conn.execute(
            """UPDATE payment SET account_id=?, amount_cents=?, currency=?, beneficiary_name=?,
               beneficiary_account_ref=?, beneficiary_is_new=?, rail=?, conversation_id=?
               WHERE id=?""",
            (
                p.account_id,
                p.amount_cents,
                p.currency,
                p.beneficiary.name,
                p.beneficiary.account_ref,
                int(p.beneficiary.is_new),
                p.rail.value,
                p.conversation_id,
                p.id,
            ),
        )
        if cur.rowcount != 1:
            raise KeyError(p.id)
