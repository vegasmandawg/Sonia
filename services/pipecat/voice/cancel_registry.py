"""Cancellation token registry for voice turns.

One cancellation token per (session_id, turn_id).
Enforces one-shot consumption: request once, consume once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class CancelToken:
    """Tracks cancellation state for a single turn."""
    requested: bool = False
    consumed: bool = False


class CancelRegistry:
    """Thread-safe registry of cancellation tokens.

    Usage:
        registry = CancelRegistry()
        registry.request("s1", "t1")   # -> True  (first request)
        registry.request("s1", "t1")   # -> False (already requested)
        registry.consume("s1", "t1")   # -> True  (first consume)
        registry.consume("s1", "t1")   # -> False (already consumed)
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._tokens: dict[tuple[str, str], CancelToken] = {}

    def request(self, session_id: str, turn_id: str) -> bool:
        """Request cancellation. Returns True if this is the first request."""
        with self._lock:
            key = (session_id, turn_id)
            tok = self._tokens.setdefault(key, CancelToken())
            if tok.requested:
                return False
            tok.requested = True
            return True

    def consume(self, session_id: str, turn_id: str) -> bool:
        """Consume the cancellation token. Returns True if successfully consumed.

        One-shot: returns False if not requested or already consumed.
        """
        with self._lock:
            tok = self._tokens.get((session_id, turn_id))
            if not tok or not tok.requested or tok.consumed:
                return False
            tok.consumed = True
            return True

    def is_requested(self, session_id: str, turn_id: str) -> bool:
        """Check if cancellation has been requested (without consuming)."""
        with self._lock:
            tok = self._tokens.get((session_id, turn_id))
            return tok is not None and tok.requested

    def is_consumed(self, session_id: str, turn_id: str) -> bool:
        """Check if cancellation token has been consumed."""
        with self._lock:
            tok = self._tokens.get((session_id, turn_id))
            return tok is not None and tok.consumed

    def clear(self, session_id: str, turn_id: str) -> None:
        """Remove token for a completed turn."""
        with self._lock:
            self._tokens.pop((session_id, turn_id), None)

    def clear_session(self, session_id: str) -> int:
        """Remove all tokens for a session. Returns count removed."""
        with self._lock:
            keys = [k for k in self._tokens if k[0] == session_id]
            for k in keys:
                del self._tokens[k]
            return len(keys)

    @property
    def active_count(self) -> int:
        """Number of active (requested but not consumed) tokens."""
        with self._lock:
            return sum(1 for t in self._tokens.values() if t.requested and not t.consumed)
