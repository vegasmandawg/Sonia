"""
API Gateway — Session Manager with Durable Persistence (M2)

In-memory session registry with configurable TTL + write-through
to memory-engine SQLite for survival across restarts.

The in-memory dict is the fast-path. Persistence is best-effort
(failures log warnings but don't block session operations).
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Any

logger = logging.getLogger("api-gateway.sessions")

DEFAULT_TTL_SECONDS = 1800          # 30 min
MAX_CONCURRENT_SESSIONS = 100
IDLE_TIMEOUT_SECONDS = 600          # 10 min without activity
PERSIST_INTERVAL_TOUCHES = 5        # persist every N touches
PERSIST_INTERVAL_SECONDS = 60       # or every N seconds


class Session:
    """A single in-memory session record."""

    __slots__ = (
        "session_id", "user_id", "conversation_id", "profile",
        "status", "created_at", "expires_at", "last_activity",
        "turn_count", "active_streams", "metadata",
        "_dirty", "_last_persist_time",
    )

    def __init__(
        self,
        user_id: str,
        conversation_id: str,
        profile: str = "chat_low_latency",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
        created_at: Optional[str] = None,
        expires_at: Optional[str] = None,
        last_activity: Optional[str] = None,
        turn_count: int = 0,
        status: str = "active",
    ):
        now = datetime.now(timezone.utc)
        self.session_id = session_id or f"ses_{uuid.uuid4().hex[:16]}"
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.profile = profile
        self.status = status
        self.created_at = created_at or now.isoformat()
        self.expires_at = expires_at or (now + timedelta(seconds=ttl_seconds)).isoformat()
        self.last_activity = last_activity or now.isoformat()
        self.turn_count = turn_count
        self.active_streams = 0
        self.metadata = metadata or {}
        self._dirty = 0  # touch counter since last persist
        self._last_persist_time = time.monotonic()

    def touch(self):
        self.last_activity = datetime.now(timezone.utc).isoformat()
        self._dirty += 1

    @property
    def needs_persist(self) -> bool:
        """True if session should be flushed to durable storage."""
        if self._dirty >= PERSIST_INTERVAL_TOUCHES:
            return True
        if self._dirty > 0 and (time.monotonic() - self._last_persist_time) > PERSIST_INTERVAL_SECONDS:
            return True
        return False

    def mark_persisted(self):
        self._dirty = 0
        self._last_persist_time = time.monotonic()

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc).isoformat() > self.expires_at

    @property
    def is_idle_timeout(self) -> bool:
        last = datetime.fromisoformat(self.last_activity)
        return (datetime.now(timezone.utc) - last).total_seconds() > IDLE_TIMEOUT_SECONDS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "profile": self.profile,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_activity": self.last_activity,
            "turn_count": self.turn_count,
            "active_streams": self.active_streams,
            "metadata": self.metadata,
        }

    def close(self):
        self.status = "closed"
        self.touch()


class SessionManager:
    """In-memory session registry with TTL, concurrency limits, and durable persistence."""

    def __init__(
        self,
        max_sessions: int = MAX_CONCURRENT_SESSIONS,
        default_ttl: int = DEFAULT_TTL_SECONDS,
        memory_client=None,
    ):
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._max = max_sessions
        self._default_ttl = default_ttl
        self._memory_client = memory_client  # set via set_memory_client()

    def set_memory_client(self, client) -> None:
        """Inject memory client for persistence (called from lifespan)."""
        self._memory_client = client

    async def restore_sessions(self) -> int:
        """Restore active sessions from memory-engine on startup. Returns count restored."""
        if not self._memory_client:
            return 0
        try:
            records = await self._memory_client.load_active_sessions()
            count = 0
            for rec in records:
                sess = Session(
                    user_id=rec["user_id"],
                    conversation_id=rec["conversation_id"],
                    profile=rec.get("profile", "chat_low_latency"),
                    session_id=rec["session_id"],
                    created_at=rec.get("created_at"),
                    expires_at=rec.get("expires_at"),
                    last_activity=rec.get("last_activity"),
                    turn_count=rec.get("turn_count", 0),
                    status=rec.get("status", "active"),
                    metadata=rec.get("metadata"),
                )
                sess.mark_persisted()
                # Only restore if not already expired
                if not sess.is_expired and not sess.is_idle_timeout:
                    self._sessions[sess.session_id] = sess
                    count += 1
            logger.info("Restored %d active sessions from durable storage", count)
            return count
        except Exception as e:
            logger.warning("Session restore failed (non-fatal): %s", e)
            return 0

    async def _persist_session(self, sess: Session) -> None:
        """Write session to durable storage (best-effort)."""
        if not self._memory_client:
            return
        try:
            await self._memory_client.persist_session(sess.to_dict())
            sess.mark_persisted()
        except Exception as e:
            logger.warning("Session persist failed for %s: %s", sess.session_id, e)

    async def _persist_session_update(self, sess: Session, updates: Dict[str, Any]) -> None:
        """Update session fields in durable storage (best-effort)."""
        if not self._memory_client:
            return
        try:
            await self._memory_client.update_session(sess.session_id, updates)
            sess.mark_persisted()
        except Exception as e:
            logger.warning("Session update persist failed for %s: %s", sess.session_id, e)

    async def create(
        self,
        user_id: str,
        conversation_id: str,
        profile: str = "chat_low_latency",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        async with self._lock:
            self._gc_expired()
            active = sum(1 for s in self._sessions.values() if s.status == "active")
            if active >= self._max:
                raise RuntimeError(
                    f"Max concurrent sessions ({self._max}) reached"
                )
            sess = Session(
                user_id=user_id,
                conversation_id=conversation_id,
                profile=profile,
                ttl_seconds=self._default_ttl,
                metadata=metadata,
            )
            self._sessions[sess.session_id] = sess
            logger.info("session created: %s user=%s", sess.session_id, user_id)

        # Persist outside lock (best-effort, non-blocking)
        asyncio.create_task(self._persist_session(sess))
        return sess

    async def get(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess and sess.status == "active":
                if sess.is_expired or sess.is_idle_timeout:
                    sess.status = "expired"
                    logger.info("session expired on access: %s", session_id)
            return sess

    async def delete(self, session_id: str) -> Optional[Session]:
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.close()
                logger.info("session closed: %s", session_id)

        # Persist status change
        if sess:
            asyncio.create_task(self._persist_session_update(sess, {"status": "closed"}))
        return sess

    async def touch(self, session_id: str):
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess and sess.status == "active":
                sess.touch()
                if sess.needs_persist:
                    asyncio.create_task(self._persist_session_update(
                        sess, {"last_activity": sess.last_activity, "turn_count": sess.turn_count}
                    ))

    async def increment_turn(self, session_id: str):
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.turn_count += 1
                sess.touch()
                if sess.needs_persist:
                    asyncio.create_task(self._persist_session_update(
                        sess, {"last_activity": sess.last_activity, "turn_count": sess.turn_count}
                    ))

    async def adjust_streams(self, session_id: str, delta: int):
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.active_streams = max(0, sess.active_streams + delta)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.status == "active")

    def _gc_expired(self):
        for s in list(self._sessions.values()):
            if s.status == "active" and (s.is_expired or s.is_idle_timeout):
                s.status = "expired"
