"""
db.py — WAL-mode SQLite database layer with append-only audit ledger,
atomic recovery link consumption & state transition, and persistent exceptions ledger.

=============================================================================
PRODUCTION SCALING ARCHITECTURE DISCLOSURE (FIX 8):
=============================================================================
SQLite with Write-Ahead Logging (WAL) is a deliberate architectural choice
for hackathon scope to provide zero-dependency portability and atomic single-file
persistence. 

For high-throughput (>1,000 TPS) horizontally-scaled production environments:
1. Replace SQLite with PostgreSQL (utilizing row-level locks & connection pooling).
2. Store active incidents, circuit breaker states, and sliding-window CUSUM drift
   counters in Redis for sub-millisecond multi-worker state synchronization.
=============================================================================
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import aiosqlite

from schemas import (
    AuditEntry,
    AuditEventType,
    ErrorCode,
    GuardrailOutcome,
    PaymentRail,
    RecoveryLinkPayload,
    TransactionRecord,
    TransactionState,
)

DB_PATH = os.environ.get("CASCADE_DB_PATH", "./cascade_heal.db")


@asynccontextmanager
async def get_db_conn() -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
    finally:
        await conn.close()


async def init_db() -> None:
    async with get_db_conn() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                rail TEXT NOT NULL,
                amount_inr REAL NOT NULL,
                state TEXT NOT NULL,
                error_code TEXT,
                recovery_link_id TEXT,
                recovery_link_expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS recovery_links (
                link_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE,
                customer_id TEXT NOT NULL,
                amount_inr REAL NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (order_id) REFERENCES transactions(order_id)
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                rail TEXT,
                order_id TEXT,
                customer_id TEXT,
                payload_json TEXT NOT NULL,
                guardrail_outcome TEXT,
                guardrail_reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                rail TEXT NOT NULL,
                classification TEXT NOT NULL,
                confidence REAL NOT NULL,
                blast_radius INTEGER NOT NULL,
                description TEXT NOT NULL,
                action_taken TEXT NOT NULL,
                target_rail TEXT,
                started_at TIMESTAMP NOT NULL,
                resolved INTEGER DEFAULT 0
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS exceptions_ledger (
                id TEXT PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                rail TEXT NOT NULL,
                order_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                classification TEXT NOT NULL,
                violated_rule TEXT,
                status TEXT NOT NULL
            );
        """)

        await conn.commit()


async def create_transaction(conn: aiosqlite.Connection, record: TransactionRecord) -> None:
    await conn.execute(
        """
        INSERT INTO transactions (order_id, customer_id, rail, amount_inr, state, error_code, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.order_id,
            record.customer_id,
            record.rail.value,
            record.amount_inr,
            record.state.value,
            record.error_code.value if record.error_code else None,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
        ),
    )
    await conn.commit()


async def get_transaction(conn: aiosqlite.Connection, order_id: str) -> TransactionRecord | None:
    async with conn.execute(
        "SELECT * FROM transactions WHERE order_id = ?", (order_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
        return TransactionRecord(
            order_id=row["order_id"],
            customer_id=row["customer_id"],
            rail=PaymentRail(row["rail"]),
            amount_inr=row["amount_inr"],
            state=TransactionState(row["state"]),
            error_code=ErrorCode(row["error_code"]) if row["error_code"] else None,
            recovery_link_id=row["recovery_link_id"],
            recovery_link_expires_at=datetime.fromisoformat(row["recovery_link_expires_at"])
            if row["recovery_link_expires_at"]
            else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


async def atomic_state_transition(
    conn: aiosqlite.Connection,
    order_id: str,
    from_state: TransactionState,
    to_state: TransactionState,
    recovery_link_id: str | None = None,
    recovery_link_expires_at: datetime | None = None,
) -> bool:
    # FIX 6: Use datetime.now(timezone.utc) instead of datetime.utcnow()
    now = datetime.now(timezone.utc).isoformat()
    expires_str = recovery_link_expires_at.isoformat() if recovery_link_expires_at else None

    if recovery_link_id:
        cursor = await conn.execute(
            """
            UPDATE transactions
            SET state = ?, recovery_link_id = ?, recovery_link_expires_at = ?, updated_at = ?
            WHERE order_id = ? AND state = ?
            """,
            (to_state.value, recovery_link_id, expires_str, now, order_id, from_state.value),
        )
    else:
        cursor = await conn.execute(
            """
            UPDATE transactions
            SET state = ?, updated_at = ?
            WHERE order_id = ? AND state = ?
            """,
            (to_state.value, now, order_id, from_state.value),
        )

    await conn.commit()
    return cursor.rowcount == 1


async def create_recovery_link(conn: aiosqlite.Connection, payload: RecoveryLinkPayload) -> bool:
    try:
        await conn.execute(
            """
            INSERT INTO recovery_links (link_id, order_id, customer_id, amount_inr, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.link_id,
                payload.order_id,
                payload.customer_id,
                payload.amount_inr,
                payload.expires_at.isoformat(),
            ),
        )
        await conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


async def consume_recovery_link(conn: aiosqlite.Connection, link_id: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    async with conn.execute(
        "SELECT * FROM recovery_links WHERE link_id = ? AND used_at IS NULL AND expires_at > ?",
        (link_id, now),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None

    update_cursor = await conn.execute(
        "UPDATE recovery_links SET used_at = ? WHERE link_id = ? AND used_at IS NULL",
        (now, link_id),
    )
    if update_cursor.rowcount == 0:
        return None

    await conn.commit()
    return dict(row)


async def consume_recovery_link_and_transition(
    conn: aiosqlite.Connection,
    order_id: str,
    link_id: str,
    from_state: TransactionState = TransactionState.RECOVERY_PENDING,
    to_state: TransactionState = TransactionState.RECOVERED,
) -> tuple[bool, dict | None, str | None]:
    """
    Atomic Recovery Link Consumption and Transaction State Transition.
    Executes link consumption AND state update inside a SINGLE database transaction.
    """
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute("BEGIN IMMEDIATE TRANSACTION;")
    try:
        async with conn.execute(
            "SELECT * FROM recovery_links WHERE link_id = ? AND used_at IS NULL AND expires_at > ?",
            (link_id, now),
        ) as cursor:
            link_row = await cursor.fetchone()
            if not link_row:
                await conn.execute("ROLLBACK;")
                return False, None, "LINK_EXPIRED_OR_USED"

        update_link = await conn.execute(
            "UPDATE recovery_links SET used_at = ? WHERE link_id = ? AND used_at IS NULL",
            (now, link_id),
        )
        if update_link.rowcount == 0:
            await conn.execute("ROLLBACK;")
            return False, None, "LINK_ALREADY_CONSUMED"

        update_txn = await conn.execute(
            "UPDATE transactions SET state = ?, updated_at = ? WHERE order_id = ? AND state = ?",
            (to_state.value, now, order_id, from_state.value),
        )

        if update_txn.rowcount == 0:
            await conn.execute("ROLLBACK;")
            return False, None, "STATE_TRANSITION_CONFLICT"

        await conn.commit()
        return True, dict(link_row), None
    except Exception as e:
        await conn.execute("ROLLBACK;")
        return False, None, str(e)


async def append_audit(conn: aiosqlite.Connection, entry: AuditEntry) -> int:
    ts = entry.timestamp.isoformat() if entry.timestamp else datetime.now(timezone.utc).isoformat()
    cursor = await conn.execute(
        """
        INSERT INTO audit_log (event_type, rail, order_id, customer_id, payload_json, guardrail_outcome, guardrail_reason, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.event_type.value if hasattr(entry.event_type, "value") else str(entry.event_type),
            entry.rail.value if entry.rail else None,
            entry.order_id,
            entry.customer_id,
            json.dumps(entry.payload),
            entry.guardrail_outcome.value if entry.guardrail_outcome else None,
            entry.guardrail_reason,
            ts,
        ),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_recent_audit_entries(conn: aiosqlite.Connection, limit: int = 50) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM audit_log ORDER BY entry_id DESC LIMIT ?", (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d["payload_json"])
            except Exception:
                d["payload"] = {}
            result.append(d)
        return result


async def get_node_error_breakdown(conn: aiosqlite.Connection, rail: str, limit: int = 50) -> dict[str, int]:
    """
    FIX 1: Real DB aggregation for node error code breakdown.
    Queries the recent audit log entries for a given payment rail and aggregates error types.
    """
    async with conn.execute(
        """
        SELECT payload_json FROM audit_log
        WHERE rail = ? AND (event_type = 'TELEMETRY_RECEIVED' OR event_type = 'GUARDRAIL_VETO')
        ORDER BY entry_id DESC LIMIT ?
        """,
        (rail, limit),
    ) as cursor:
        rows = await cursor.fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
            code = payload.get("error_code") or payload.get("reason") or "UNKNOWN_ERROR"
            counts[code] = counts.get(code, 0) + 1
        except Exception:
            pass
    return counts


async def upsert_incident(conn: aiosqlite.Connection, incident_dict: dict) -> None:
    await conn.execute(
        """
        INSERT INTO incidents (incident_id, rail, classification, confidence, blast_radius, description, action_taken, target_rail, started_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(incident_id) DO UPDATE SET
            resolved = excluded.resolved,
            description = excluded.description
        """,
        (
            incident_dict["incident_id"],
            incident_dict["rail"],
            incident_dict["classification"],
            incident_dict["confidence"],
            incident_dict["blast_radius"],
            incident_dict["description"],
            incident_dict["action_taken"],
            incident_dict.get("target_rail"),
            incident_dict["started_at"],
        ),
    )
    await conn.commit()


async def get_active_db_incidents(conn: aiosqlite.Connection) -> list[dict]:
    async with conn.execute("SELECT * FROM incidents WHERE resolved = 0") as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def insert_exception_entry(conn: aiosqlite.Connection, exc: dict) -> None:
    await conn.execute(
        """
        INSERT OR IGNORE INTO exceptions_ledger (id, timestamp, rail, order_id, reason, classification, violated_rule, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exc["id"],
            exc["timestamp"],
            exc["rail"],
            exc["order_id"],
            exc["reason"],
            exc["classification"],
            exc.get("violated_rule"),
            exc["status"],
        ),
    )
    await conn.commit()


async def get_exceptions_from_db(conn: aiosqlite.Connection, limit: int = 50) -> list[dict]:
    async with conn.execute(
        "SELECT * FROM exceptions_ledger ORDER BY timestamp DESC LIMIT ?", (limit,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
