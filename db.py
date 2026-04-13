"""
SQLite database helper for AI-PA CRM.
Handles pending approvals, event log, and chat history.
Swap to Postgres later by changing the connection in get_db().
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'crm.db')


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # safe for concurrent reads/writes
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_approvals (
                id              TEXT PRIMARY KEY,
                identifier      TEXT,
                identifier_type TEXT,
                channel         TEXT,
                sender_name     TEXT,
                original_message TEXT,
                analysis        TEXT,
                draft           TEXT,
                status          TEXT DEFAULT 'pending',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS event_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier      TEXT,
                identifier_type TEXT,
                channel         TEXT,
                direction       TEXT,
                event_type      TEXT,
                note            TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                question    TEXT,
                answer      TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );
        """)


# ------------------------------------------------------------------
# Pending approvals
# ------------------------------------------------------------------

def create_approval(approval_id: str, identifier: str, identifier_type: str,
                    channel: str, sender_name: str, original_message: str,
                    analysis: str, draft: str):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO pending_approvals
                (id, identifier, identifier_type, channel, sender_name,
                 original_message, analysis, draft)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (approval_id, identifier, identifier_type, channel, sender_name,
              original_message, analysis, draft))


def get_approvals(status: str = 'pending') -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_approvals WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_approval(approval_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM pending_approvals WHERE id = ?", (approval_id,)
        ).fetchone()
        return dict(row) if row else None


def update_approval(approval_id: str, **kwargs):
    kwargs['updated_at'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    fields = ', '.join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [approval_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE pending_approvals SET {fields} WHERE id = ?", values
        )


# ------------------------------------------------------------------
# Event log
# ------------------------------------------------------------------

def log_event(identifier: str, identifier_type: str, channel: str,
              direction: str, event_type: str, note: str = ''):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO event_log
                (identifier, identifier_type, channel, direction, event_type, note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (identifier, identifier_type, channel, direction, event_type, note))


def get_event_log(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM event_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Chat history
# ------------------------------------------------------------------

def save_chat(question: str, answer: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO chat_history (question, answer) VALUES (?, ?)",
            (question, answer)
        )


def get_chat_history(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_history ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


# Initialise on import
init_db()
