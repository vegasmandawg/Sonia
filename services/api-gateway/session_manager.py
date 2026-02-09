"""
API Gateway — In-Memory Session Manager (Stage 3)

Provides create / get / delete / expire for lightweight sessions.
Sessions are kept in-memory with configurable TTL.
Thread-safe via asyncio lock (single-process uvicorn).
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


class Session:
    """A single in-memory session record."""

    __slots__ = (
        "session_id", "user_id", "conversation_id", "profile",
        "status", "created_at", "expires_at", "last_activity",
        "turn_count", "active_streams", "metadata",
    )

    def __init__(
        self,
        user_id: str,
        conversation_id: str,
        profile: str = "chat_low_latency",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        now = datetime.now(timezone.utc)
        self.session_id = f"ses_{uuid.uuid4().hex[:16]}"
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.profile = profile
        self.status = "active"
        self.created_at = now.isoformat()
        self.expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        self.last_activity = now.isoformat()
        self.turn_count = 0
        self.active_streams = 0
        self.metadata = metadata or {}

    def touch(self):
        self.last_activity = datetime.now(timezone.utc).isoformat()

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
    """In-memory session registry with TTL and concurrency limits."""

    def __init__(
        self,
        max_sessions: int = MAX_CONCURRENT_SESSIONS,
        default_ttl: int = DEFAULT_TTL_SECONDS,
    ):
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._max = max_sessions
        self._default_ttl = default_ttl

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
            return sess

    async def touch(self, session_id: str):
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess and sess.status == "active":
                sess.touch()

    async def increment_turn(self, session_id: str):
        async with self._lock:
            sess = self._sessions.get(session_id)
            if sess:
                sess.turn_count += 1
                sess.touch()

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
