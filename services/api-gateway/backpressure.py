"""
Backpressure Policy (v4.3 Epic C)

Prevents queue blow-up during barge-in storms.
Shed oldest frames when queue depth exceeds threshold.
Track metrics for latency gate.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict


class BackpressurePolicy:
    """
    Per-session queue depth limiter with oldest-first shedding.

    When a session's queue depth reaches max_queue_depth, the oldest
    item is evicted before the new one is admitted. This prevents
    unbounded queue growth during barge-in storms while ensuring
    the most recent items are always processed.

    Thread-safe via lock.
    """

    def __init__(
        self,
        max_queue_depth: int = 10,
        shed_strategy: str = "oldest",
    ) -> None:
        if max_queue_depth < 1:
            raise ValueError("max_queue_depth must be >= 1")
        self._max_depth = max_queue_depth
        self._shed_strategy = shed_strategy  # currently only "oldest" supported
        self._queues: Dict[str, Deque[Dict[str, Any]]] = {}
        self._admit_count = 0
        self._shed_count = 0
        self._lock = threading.Lock()

    # -- core API -----------------------------------------------------------

    def admit(self, item: Any, session_id: str) -> bool:
        """
        Try to admit an item into the session's queue.

        If queue depth is at max, shed the oldest item first,
        then admit the new one. Returns True if the item was
        admitted (always True with oldest shedding -- the shed
        happens transparently). Returns False only if shedding
        itself fails (should not happen).
        """
        with self._lock:
            if session_id not in self._queues:
                self._queues[session_id] = deque()

            q = self._queues[session_id]

            # Shed oldest if at capacity
            if len(q) >= self._max_depth:
                q.popleft()
                self._shed_count += 1

            entry = {
                "item": item,
                "session_id": session_id,
                "admitted_at": time.time(),
            }
            q.append(entry)
            self._admit_count += 1
            return True

    def dequeue(self, session_id: str) -> Any:
        """
        Remove and return the oldest item from a session's queue.
        Returns None if queue is empty or session not found.
        """
        with self._lock:
            q = self._queues.get(session_id)
            if not q:
                return None
            entry = q.popleft()
            return entry.get("item")

    def reset_session(self, session_id: str) -> int:
        """
        Clear all queued items for a session (e.g. on barge-in).
        Returns the number of items that were dropped.
        """
        with self._lock:
            q = self._queues.pop(session_id, None)
            if q is None:
                return 0
            dropped = len(q)
            self._shed_count += dropped
            return dropped

    # -- introspection ------------------------------------------------------

    @property
    def shed_count(self) -> int:
        """Total number of items shed across all sessions."""
        return self._shed_count

    @property
    def admit_count(self) -> int:
        """Total number of items admitted across all sessions."""
        return self._admit_count

    def per_session_depth(self, session_id: str) -> int:
        """Current queue depth for a given session."""
        with self._lock:
            q = self._queues.get(session_id)
            return len(q) if q else 0

    def get_metrics(self) -> Dict[str, Any]:
        """
        Return operational metrics snapshot.

        Includes total counts, per-session depths, and shed rate.
        """
        with self._lock:
            total_depth = sum(len(q) for q in self._queues.values())
            per_session = {
                sid: len(q) for sid, q in self._queues.items()
            }
            total_ops = self._admit_count + self._shed_count
            shed_rate = (
                self._shed_count / total_ops if total_ops > 0 else 0.0
            )
            return {
                "admit_count": self._admit_count,
                "shed_count": self._shed_count,
                "shed_rate": round(shed_rate, 4),
                "total_queue_depth": total_depth,
                "active_sessions": len(self._queues),
                "per_session_depth": per_session,
                "max_queue_depth": self._max_depth,
                "shed_strategy": self._shed_strategy,
            }
