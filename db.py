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


# ------------------------------------------------------------------
# Token encryption (Fernet, per-tenant key via env)
# ------------------------------------------------------------------
# TENANT_ENCRYPTION_KEY is a urlsafe base64-encoded 32-byte key generated
# per tenant at provision time. It encrypts Meta access tokens at rest so a
# dump of crm.db alone doesn't expose them.

from cryptography.fernet import Fernet, InvalidToken  # noqa: E402

_FERNET = None


def _fernet() -> Fernet:
    global _FERNET
    if _FERNET is None:
        key = os.environ.get('TENANT_ENCRYPTION_KEY')
        if not key:
            raise RuntimeError(
                "TENANT_ENCRYPTION_KEY env var is not set. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _FERNET = Fernet(key.encode() if isinstance(key, str) else key)
    return _FERNET


def encrypt_secret(text: str) -> str:
    if text is None:
        return None
    return _fernet().encrypt(text.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    if ciphertext is None:
        return None
    return _fernet().decrypt(ciphertext.encode()).decode()


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
                kind            TEXT DEFAULT 'inbound',
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
        # Migration: add kind column to existing databases
        try:
            conn.execute("ALTER TABLE pending_approvals ADD COLUMN kind TEXT DEFAULT 'inbound'")
        except sqlite3.OperationalError:
            pass  # column already exists

        # Migration: 24h window anchor + manual-send state for Meta channels
        for col_sql in (
            "ALTER TABLE pending_approvals ADD COLUMN last_inbound_at TEXT",
            "ALTER TABLE pending_approvals ADD COLUMN manual_send_state TEXT",
            "ALTER TABLE pending_approvals ADD COLUMN thread_id TEXT",
        ):
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass

        # Migration: auto-approval pattern tracking
        for col_sql in (
            "ALTER TABLE pending_approvals ADD COLUMN intent_label TEXT",
            "ALTER TABLE pending_approvals ADD COLUMN was_edited INTEGER DEFAULT 0",
            "ALTER TABLE pending_approvals ADD COLUMN error_note TEXT",
        ):
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                request     TEXT NOT NULL,
                workaround  TEXT,
                frequency   TEXT,
                importance  TEXT,
                tenant      TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS calendar_events (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                start_at        TEXT NOT NULL,
                end_at          TEXT,
                event_type      TEXT DEFAULT 'meeting',
                client_name     TEXT,
                client_identifier TEXT,
                location        TEXT,
                notes           TEXT,
                status          TEXT DEFAULT 'scheduled',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS channel_connections (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                channel                 TEXT NOT NULL,   -- 'messenger' | 'instagram'
                page_id                 TEXT,
                page_name               TEXT,
                page_username           TEXT,
                ig_business_account_id  TEXT,
                access_token_encrypted  TEXT,
                scopes                  TEXT,
                status                  TEXT DEFAULT 'connected',  -- 'connected' | 'needs_reconnect' | 'disconnected'
                connected_at            TEXT DEFAULT (datetime('now')),
                last_validated_at       TEXT,
                UNIQUE(channel)
            );

            CREATE TABLE IF NOT EXISTS message_threads (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                channel         TEXT NOT NULL,
                identifier      TEXT NOT NULL,   -- PSID for Messenger, IGSID for Instagram
                thread_id       TEXT,            -- Instagram thread ID if resolvable
                page_id         TEXT,
                last_inbound_at TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(channel, identifier)
            );

            CREATE TABLE IF NOT EXISTS response_patterns (
                intent_label    TEXT PRIMARY KEY,
                status          TEXT DEFAULT 'learning',   -- 'learning' | 'auto' | 'manual_locked'
                promoted_at     TEXT,
                demoted_at      TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                last_seen_at    TEXT
            );
        """)


# ------------------------------------------------------------------
# Pending approvals
# ------------------------------------------------------------------

def create_approval(approval_id: str, identifier: str, identifier_type: str,
                    channel: str, sender_name: str, original_message: str,
                    analysis: str, draft: str, kind: str = 'inbound',
                    last_inbound_at: str = None, thread_id: str = None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO pending_approvals
                (id, identifier, identifier_type, channel, sender_name,
                 original_message, analysis, draft, kind,
                 last_inbound_at, thread_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (approval_id, identifier, identifier_type, channel, sender_name,
              original_message, analysis, draft, kind,
              last_inbound_at, thread_id))


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


# ------------------------------------------------------------------
# Feedback
# ------------------------------------------------------------------

def create_feedback(request: str, workaround: str, frequency: str,
                    importance: str, tenant: str = '') -> int:
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO feedback (request, workaround, frequency, importance, tenant)
            VALUES (?, ?, ?, ?, ?)
        """, (request, workaround, frequency, importance, tenant))
        return cur.lastrowid


def get_feedback(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ------------------------------------------------------------------
# Calendar events
# ------------------------------------------------------------------

def create_calendar_event(event_id: str, title: str, start_at: str,
                          end_at: str = None, event_type: str = 'meeting',
                          client_name: str = '', client_identifier: str = '',
                          location: str = '', notes: str = '',
                          status: str = 'scheduled'):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO calendar_events
                (id, title, start_at, end_at, event_type,
                 client_name, client_identifier, location, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, title, start_at, end_at, event_type,
              client_name, client_identifier, location, notes, status))


def get_calendar_events(from_date: str, to_date: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM calendar_events
            WHERE start_at >= ? AND start_at < ? AND status != 'cancelled'
            ORDER BY start_at
        """, (from_date, to_date)).fetchall()
        return [dict(r) for r in rows]


def get_calendar_event(event_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM calendar_events WHERE id = ?", (event_id,)
        ).fetchone()
        return dict(row) if row else None


def update_calendar_event(event_id: str, **kwargs):
    kwargs['updated_at'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    fields = ', '.join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [event_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE calendar_events SET {fields} WHERE id = ?", values
        )


def delete_calendar_event(event_id: str):
    with get_db() as conn:
        conn.execute(
            "UPDATE calendar_events SET status = 'cancelled', updated_at = ? WHERE id = ?",
            (datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'), event_id)
        )


# ------------------------------------------------------------------
# Channel connections (Meta Messenger / Instagram)
# ------------------------------------------------------------------

def save_channel_connection(channel: str, page_id: str, page_name: str,
                            access_token: str, scopes: str = '',
                            page_username: str = '',
                            ig_business_account_id: str = ''):
    """Upsert a channel connection. Token is encrypted at rest."""
    encrypted = encrypt_secret(access_token)
    with get_db() as conn:
        conn.execute("""
            INSERT INTO channel_connections
                (channel, page_id, page_name, page_username,
                 ig_business_account_id, access_token_encrypted, scopes,
                 status, connected_at, last_validated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'connected', datetime('now'), datetime('now'))
            ON CONFLICT(channel) DO UPDATE SET
                page_id=excluded.page_id,
                page_name=excluded.page_name,
                page_username=excluded.page_username,
                ig_business_account_id=excluded.ig_business_account_id,
                access_token_encrypted=excluded.access_token_encrypted,
                scopes=excluded.scopes,
                status='connected',
                last_validated_at=datetime('now')
        """, (channel, page_id, page_name, page_username,
              ig_business_account_id, encrypted, scopes))


def get_channel_connection(channel: str, decrypt_token: bool = False) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM channel_connections WHERE channel = ?", (channel,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if decrypt_token and d.get('access_token_encrypted'):
            d['access_token'] = decrypt_secret(d['access_token_encrypted'])
        # Never leak the ciphertext to callers that don't need it
        d.pop('access_token_encrypted', None)
        return d


def list_channel_connections() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT channel, page_id, page_name, page_username, "
            "ig_business_account_id, status, connected_at, last_validated_at "
            "FROM channel_connections"
        ).fetchall()
        return [dict(r) for r in rows]


def update_channel_connection(channel: str, **kwargs):
    if not kwargs:
        return
    fields = ', '.join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [channel]
    with get_db() as conn:
        conn.execute(
            f"UPDATE channel_connections SET {fields} WHERE channel = ?", values
        )


def delete_channel_connection(channel: str):
    with get_db() as conn:
        conn.execute("DELETE FROM channel_connections WHERE channel = ?", (channel,))


# ------------------------------------------------------------------
# Message threads (per-contact last-inbound tracking)
# ------------------------------------------------------------------

def upsert_message_thread(channel: str, identifier: str, last_inbound_at: str,
                          thread_id: str = None, page_id: str = None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO message_threads
                (channel, identifier, thread_id, page_id, last_inbound_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel, identifier) DO UPDATE SET
                thread_id=COALESCE(excluded.thread_id, message_threads.thread_id),
                page_id=COALESCE(excluded.page_id, message_threads.page_id),
                last_inbound_at=excluded.last_inbound_at
        """, (channel, identifier, thread_id, page_id, last_inbound_at))


def get_message_thread(channel: str, identifier: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM message_threads WHERE channel = ? AND identifier = ?",
            (channel, identifier)
        ).fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------------
# Response patterns (auto-approval)
# ------------------------------------------------------------------

def upsert_pattern(intent_label: str):
    """Create a pattern row if absent; bump last_seen_at. No-op if intent_label is empty."""
    if not intent_label:
        return
    with get_db() as conn:
        conn.execute("""
            INSERT INTO response_patterns (intent_label, status, last_seen_at)
            VALUES (?, 'learning', datetime('now'))
            ON CONFLICT(intent_label) DO UPDATE SET
                last_seen_at = datetime('now')
        """, (intent_label,))


def get_pattern(intent_label: str) -> dict | None:
    if not intent_label:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM response_patterns WHERE intent_label = ?", (intent_label,)
        ).fetchone()
        return dict(row) if row else None


def list_patterns() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM response_patterns ORDER BY last_seen_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def set_pattern_status(intent_label: str, status: str):
    """Set status to 'learning' | 'auto' | 'manual_locked'. Updates promoted_at / demoted_at accordingly."""
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as conn:
        if status == 'auto':
            conn.execute(
                "UPDATE response_patterns SET status = ?, promoted_at = ? WHERE intent_label = ?",
                (status, now, intent_label)
            )
        elif status == 'manual_locked':
            conn.execute(
                "UPDATE response_patterns SET status = ?, demoted_at = ? WHERE intent_label = ?",
                (status, now, intent_label)
            )
        else:
            conn.execute(
                "UPDATE response_patterns SET status = ? WHERE intent_label = ?",
                (status, intent_label)
            )


def mark_approval_edited(approval_id: str):
    """Flip was_edited to 1. Idempotent."""
    with get_db() as conn:
        conn.execute(
            "UPDATE pending_approvals SET was_edited = 1 WHERE id = ?", (approval_id,)
        )


# Initialise on import
init_db()
