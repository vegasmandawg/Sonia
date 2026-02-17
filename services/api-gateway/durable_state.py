"""
API Gateway -- Durable State Store (v4.3 Epic A, v4.7 Epic B)

SQLite-backed persistence for sessions, confirmations, dead letters, and idempotency keys.
Write-through cache: in-memory dict is fast path, SQLite is crash-safe journal.

Tables:
  sessions         - session lifecycle (active, expired, closed)
  confirmations    - tool confirmation tokens (pending, approved, denied, expired)
  dead_letters     - failed action events
  outbox           - memory write-back queue (at-least-once delivery)
  idempotency_keys - durable idempotency store (v4.7 B4)
"""

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.durable_state")

DEFAULT_DB_PATH = os.path.join("S:\\", "data", "gateway_state.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    profile        TEXT NOT NULL DEFAULT 'chat_low_latency',
    status         TEXT NOT NULL DEFAULT 'active',
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    last_activity  TEXT NOT NULL,
    turn_count     INTEGER NOT NULL DEFAULT 0,
    metadata       TEXT NOT NULL DEFAULT '{}',
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS confirmations (
    confirmation_id TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    turn_id         TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    args            TEXT NOT NULL DEFAULT '{}',
    summary         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    ttl_seconds     REAL NOT NULL DEFAULT 120.0,
    decided_at      TEXT
);

CREATE TABLE IF NOT EXISTS dead_letters (
    letter_id        TEXT PRIMARY KEY,
    action_id        TEXT NOT NULL,
    intent           TEXT NOT NULL,
    params           TEXT NOT NULL DEFAULT '{}',
    error_code       TEXT NOT NULL,
    error_message    TEXT NOT NULL DEFAULT '',
    failure_class    TEXT,
    correlation_id   TEXT,
    session_id       TEXT,
    created_at       TEXT NOT NULL,
    retries_exhausted INTEGER NOT NULL DEFAULT 0,
    replayed         INTEGER NOT NULL DEFAULT 0,
    replayed_at      TEXT,
    replay_action_id TEXT
);

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id    TEXT PRIMARY KEY,
    entry_type   TEXT NOT NULL,
    payload      TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    delivered    INTEGER NOT NULL DEFAULT 0,
    delivered_at TEXT,
    attempts     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    action_id       TEXT NOT NULL,
    result_json     TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);
"""


class DurableStateStore:
    """
    SQLite-backed durable state for sessions, confirmations, dead letters,
    and an outbox for at-least-once memory write-back.

    All public methods are async-safe via run_in_executor wrapping sync sqlite3.
    Persistence failures log warnings but never raise to callers.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Internal: database lifecycle
    # ------------------------------------------------------------------

    def _init_db(self):
        """Create / open database and run migrations."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL mode for concurrent readers
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        logger.info("Durable state store opened: %s", self._db_path)

    async def _run(self, fn, *args):
        """Run a sync function in the default executor (thread pool)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn, *args)

    def close(self):
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def _persist_session_sync(self, sess: Dict[str, Any]):
        now = datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(sess.get("metadata") or {})
        self._conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, user_id, conversation_id, profile, status,
                created_at, expires_at, last_activity, turn_count, metadata, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sess["session_id"],
                sess.get("user_id", ""),
                sess.get("conversation_id", ""),
                sess.get("profile", "chat_low_latency"),
                sess.get("status", "active"),
                sess.get("created_at", now),
                sess.get("expires_at", now),
                sess.get("last_activity", now),
                sess.get("turn_count", 0),
                metadata_json,
                now,
            ),
        )
        self._conn.commit()

    async def persist_session(self, sess: Dict[str, Any]):
        """Write a full session record (INSERT OR REPLACE)."""
        try:
            await self._run(self._persist_session_sync, sess)
        except Exception as e:
            logger.warning("persist_session failed for %s: %s", sess.get("session_id"), e)

    def _update_session_sync(self, session_id: str, updates_json: str):
        updates = json.loads(updates_json)
        if not updates:
            return
        now = datetime.now(timezone.utc).isoformat()
        updates["updated_at"] = now
        set_parts = []
        values = []
        for k, v in updates.items():
            if k == "metadata":
                v = json.dumps(v)
            set_parts.append(f"{k} = ?")
            values.append(v)
        values.append(session_id)
        sql = f"UPDATE sessions SET {', '.join(set_parts)} WHERE session_id = ?"
        self._conn.execute(sql, values)
        self._conn.commit()

    async def update_session(self, session_id: str, updates: Dict[str, Any]):
        """Update specific fields on a session record."""
        try:
            await self._run(self._update_session_sync, session_id, json.dumps(updates))
        except Exception as e:
            logger.warning("update_session failed for %s: %s", session_id, e)

    def _load_active_sessions_sync(self) -> str:
        cur = self._conn.execute(
            "SELECT * FROM sessions WHERE status = 'active'"
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            # Parse metadata JSON
            try:
                d["metadata"] = json.loads(d.get("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            result.append(d)
        return json.dumps(result)

    async def load_active_sessions(self) -> List[Dict[str, Any]]:
        """Load all sessions with status='active'."""
        try:
            raw = await self._run(self._load_active_sessions_sync)
            return json.loads(raw)
        except Exception as e:
            logger.warning("load_active_sessions failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Confirmations
    # ------------------------------------------------------------------

    def _persist_confirmation_sync(self, token: Dict[str, Any]):
        args_json = json.dumps(token.get("args") or {})
        self._conn.execute(
            """INSERT OR REPLACE INTO confirmations
               (confirmation_id, session_id, turn_id, tool_name, args,
                summary, status, created_at, ttl_seconds, decided_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                token["confirmation_id"],
                token.get("session_id", ""),
                token.get("turn_id", ""),
                token.get("tool_name", ""),
                args_json,
                token.get("summary", ""),
                token.get("status", "pending"),
                token.get("created_at", datetime.now(timezone.utc).isoformat()),
                token.get("ttl_seconds", 120.0),
                token.get("decided_at"),
            ),
        )
        self._conn.commit()

    async def persist_confirmation(self, token: Dict[str, Any]):
        """Write a confirmation token to durable storage."""
        try:
            await self._run(self._persist_confirmation_sync, token)
        except Exception as e:
            logger.warning("persist_confirmation failed for %s: %s", token.get("confirmation_id"), e)

    def _update_confirmation_sync(self, confirmation_id: str, status: str, decided_at: Optional[str]):
        self._conn.execute(
            "UPDATE confirmations SET status = ?, decided_at = ? WHERE confirmation_id = ?",
            (status, decided_at, confirmation_id),
        )
        self._conn.commit()

    async def update_confirmation(self, confirmation_id: str, status: str, decided_at: Optional[str] = None):
        """Update confirmation status and decided_at timestamp."""
        try:
            await self._run(self._update_confirmation_sync, confirmation_id, status, decided_at)
        except Exception as e:
            logger.warning("update_confirmation failed for %s: %s", confirmation_id, e)

    def _load_pending_confirmations_sync(self) -> str:
        cur = self._conn.execute(
            "SELECT * FROM confirmations WHERE status = 'pending'"
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["args"] = json.loads(d.get("args") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["args"] = {}
            result.append(d)
        return json.dumps(result)

    async def load_pending_confirmations(self) -> List[Dict[str, Any]]:
        """Load all confirmations with status='pending'."""
        try:
            raw = await self._run(self._load_pending_confirmations_sync)
            return json.loads(raw)
        except Exception as e:
            logger.warning("load_pending_confirmations failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Dead Letters
    # ------------------------------------------------------------------

    def _persist_dead_letter_sync(self, dl: Dict[str, Any]):
        params_json = json.dumps(dl.get("params") or {})
        created_at = dl.get("created_at", "")
        # Handle both datetime objects and ISO strings
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat() + "Z"
        self._conn.execute(
            """INSERT OR REPLACE INTO dead_letters
               (letter_id, action_id, intent, params, error_code, error_message,
                failure_class, correlation_id, session_id, created_at,
                retries_exhausted, replayed, replayed_at, replay_action_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                dl["letter_id"],
                dl.get("action_id", ""),
                dl.get("intent", ""),
                params_json,
                dl.get("error_code", ""),
                dl.get("error_message", ""),
                dl.get("failure_class"),
                dl.get("correlation_id"),
                dl.get("session_id"),
                created_at,
                dl.get("retries_exhausted", 0),
                1 if dl.get("replayed") else 0,
                dl.get("replayed_at"),
                dl.get("replay_action_id"),
            ),
        )
        self._conn.commit()

    async def persist_dead_letter(self, dl: Dict[str, Any]):
        """Write a dead letter to durable storage."""
        try:
            await self._run(self._persist_dead_letter_sync, dl)
        except Exception as e:
            logger.warning("persist_dead_letter failed for %s: %s", dl.get("letter_id"), e)

    def _update_dead_letter_sync(self, letter_id: str, updates_json: str):
        updates = json.loads(updates_json)
        if not updates:
            return
        set_parts = []
        values = []
        for k, v in updates.items():
            if k == "params":
                v = json.dumps(v)
            elif k == "replayed":
                v = 1 if v else 0
            elif hasattr(v, "isoformat"):
                v = v.isoformat() + "Z"
            set_parts.append(f"{k} = ?")
            values.append(v)
        values.append(letter_id)
        sql = f"UPDATE dead_letters SET {', '.join(set_parts)} WHERE letter_id = ?"
        self._conn.execute(sql, values)
        self._conn.commit()

    async def update_dead_letter(self, letter_id: str, updates: Dict[str, Any]):
        """Update fields on a dead letter record."""
        try:
            # Convert datetime values to strings for JSON serialization
            serializable = {}
            for k, v in updates.items():
                if hasattr(v, "isoformat"):
                    serializable[k] = v.isoformat() + "Z"
                else:
                    serializable[k] = v
            await self._run(self._update_dead_letter_sync, letter_id, json.dumps(serializable))
        except Exception as e:
            logger.warning("update_dead_letter failed for %s: %s", letter_id, e)

    def _load_dead_letters_sync(self) -> str:
        cur = self._conn.execute(
            "SELECT * FROM dead_letters WHERE replayed = 0"
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["params"] = json.loads(d.get("params") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["params"] = {}
            d["replayed"] = bool(d.get("replayed", 0))
            result.append(d)
        return json.dumps(result)

    async def load_dead_letters(self) -> List[Dict[str, Any]]:
        """Load all non-replayed dead letters."""
        try:
            raw = await self._run(self._load_dead_letters_sync)
            return json.loads(raw)
        except Exception as e:
            logger.warning("load_dead_letters failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Outbox (memory write-back queue)
    # ------------------------------------------------------------------

    def _enqueue_outbox_sync(self, outbox_id: str, entry_type: str, payload_json: str, created_at: str):
        self._conn.execute(
            """INSERT INTO outbox (outbox_id, entry_type, payload, created_at, delivered, attempts)
               VALUES (?, ?, ?, ?, 0, 0)""",
            (outbox_id, entry_type, payload_json, created_at),
        )
        self._conn.commit()

    async def enqueue_outbox(self, entry_type: str, payload: Dict[str, Any]) -> str:
        """Add an entry to the outbox queue. Returns outbox_id."""
        outbox_id = f"obx_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, default=str)
        try:
            await self._run(self._enqueue_outbox_sync, outbox_id, entry_type, payload_json, now)
        except Exception as e:
            logger.warning("enqueue_outbox failed: %s", e)
        return outbox_id

    def _get_pending_outbox_sync(self, limit: int) -> str:
        cur = self._conn.execute(
            "SELECT * FROM outbox WHERE delivered = 0 ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["payload"] = json.loads(d.get("payload") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
            d["delivered"] = bool(d.get("delivered", 0))
            result.append(d)
        return json.dumps(result, default=str)

    async def get_pending_outbox(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get undelivered outbox entries, oldest first."""
        try:
            raw = await self._run(self._get_pending_outbox_sync, limit)
            return json.loads(raw)
        except Exception as e:
            logger.warning("get_pending_outbox failed: %s", e)
            return []

    def _mark_delivered_sync(self, outbox_id: str):
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE outbox SET delivered = 1, delivered_at = ?, attempts = attempts + 1 WHERE outbox_id = ?",
            (now, outbox_id),
        )
        self._conn.commit()

    async def mark_delivered(self, outbox_id: str):
        """Mark an outbox entry as successfully delivered."""
        try:
            await self._run(self._mark_delivered_sync, outbox_id)
        except Exception as e:
            logger.warning("mark_delivered failed for %s: %s", outbox_id, e)

    def _increment_attempt_sync(self, outbox_id: str):
        self._conn.execute(
            "UPDATE outbox SET attempts = attempts + 1 WHERE outbox_id = ?",
            (outbox_id,),
        )
        self._conn.commit()

    async def increment_attempt(self, outbox_id: str):
        """Increment the attempt counter for a failed delivery."""
        try:
            await self._run(self._increment_attempt_sync, outbox_id)
        except Exception as e:
            logger.warning("increment_attempt failed for %s: %s", outbox_id, e)

    # ------------------------------------------------------------------
    # Idempotency Keys (v4.7 Epic B — durable idempotency_store)
    # ------------------------------------------------------------------
    # IdempotencyStore is integrated into DurableStateStore (not a separate class)
    # Table: idempotency_keys — SQLite-backed, TTL-expiring, write-through

    def _persist_idempotency_key_sync(self, key: str, action_id: str, result_json: str, created_at: str, expires_at: str):
        self._conn.execute(
            """INSERT OR REPLACE INTO idempotency_keys
               (idempotency_key, action_id, result_json, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (key, action_id, result_json, created_at, expires_at),
        )
        self._conn.commit()

    async def persist_idempotency_key(self, key: str, action_id: str, result: Dict[str, Any], ttl_seconds: float = 300.0):
        """Write an idempotency key mapping to durable storage with TTL."""
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        from datetime import timedelta
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        result_json = json.dumps(result, default=str)
        try:
            await self._run(self._persist_idempotency_key_sync, key, action_id, result_json, created_at, expires_at)
        except Exception as e:
            logger.warning("persist_idempotency_key failed for %s: %s", key, e)

    def _get_idempotency_key_sync(self, key: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "SELECT * FROM idempotency_keys WHERE idempotency_key = ? AND expires_at > ?",
            (key, now),
        )
        row = cur.fetchone()
        if row is None:
            return json.dumps(None)
        d = dict(row)
        try:
            d["result_json"] = json.loads(d.get("result_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["result_json"] = {}
        return json.dumps(d)

    async def get_idempotency_key(self, key: str) -> Optional[Dict[str, Any]]:
        """Look up a non-expired idempotency key. Returns None if not found or expired."""
        try:
            raw = await self._run(self._get_idempotency_key_sync, key)
            return json.loads(raw)
        except Exception as e:
            logger.warning("get_idempotency_key failed for %s: %s", key, e)
            return None

    def _prune_expired_idempotency_keys_sync(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "DELETE FROM idempotency_keys WHERE expires_at <= ?",
            (now,),
        )
        self._conn.commit()
        return cur.rowcount

    async def prune_expired_idempotency_keys(self) -> int:
        """Remove expired idempotency keys. Returns count deleted."""
        try:
            return await self._run(self._prune_expired_idempotency_keys_sync)
        except Exception as e:
            logger.warning("prune_expired_idempotency_keys failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Bulk restore (startup convenience)
    # ------------------------------------------------------------------

    async def restore_all(self) -> Dict[str, int]:
        """
        Load all active state counts for startup diagnostics.
        Returns counts of active sessions, pending confirmations, unresolved dead letters, pending outbox.
        """
        sessions = await self.load_active_sessions()
        confirmations = await self.load_pending_confirmations()
        dead_letters = await self.load_dead_letters()
        outbox = await self.get_pending_outbox(limit=9999)
        return {
            "sessions": len(sessions),
            "confirmations": len(confirmations),
            "dead_letters": len(dead_letters),
            "outbox_pending": len(outbox),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_store: Optional[DurableStateStore] = None


def get_durable_state_store(db_path: str = DEFAULT_DB_PATH) -> DurableStateStore:
    """Get or create the singleton DurableStateStore."""
    global _store
    if _store is None:
        _store = DurableStateStore(db_path=db_path)
    return _store
