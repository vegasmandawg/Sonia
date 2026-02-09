"""
Model Router - Backend Health Registry

Tracks backend health with rolling failure windows, temporary quarantine,
and probe-based re-entry.  Designed to plug into the RoutingEngine as the
``is_healthy`` callback.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("model-router.health-registry")


# ---------------------------------------------------------------------------
# Backend state
# ---------------------------------------------------------------------------

class BackendState(str, Enum):
    HEALTHY     = "healthy"
    DEGRADED    = "degraded"
    QUARANTINED = "quarantined"
    UNKNOWN     = "unknown"


@dataclass
class FailureRecord:
    """A single recorded failure event."""
    timestamp: float
    error: str = ""


@dataclass
class BackendHealth:
    """Health state for a single backend."""
    backend: str
    state: BackendState = BackendState.UNKNOWN
    failures: List[FailureRecord] = field(default_factory=list)
    quarantine_until: float = 0.0
    consecutive_successes: int = 0
    total_successes: int = 0
    total_failures: int = 0
    last_check: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backend": self.backend,
            "state": self.state.value,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "consecutive_successes": self.consecutive_successes,
            "quarantine_until": self.quarantine_until,
            "recent_failures": len(self.failures),
        }


# ---------------------------------------------------------------------------
# Health registry
# ---------------------------------------------------------------------------

class HealthRegistry:
    """
    Thread-safe registry tracking per-backend health.

    Parameters
    ----------
    failure_window_s : float
        Rolling window (seconds) for counting recent failures.
    failure_threshold : int
        Number of failures within the window that triggers quarantine.
    quarantine_s : float
        Duration of quarantine (seconds).
    recovery_probes : int
        Consecutive successes needed to exit quarantine.
    """

    def __init__(
        self,
        failure_window_s: float = 60.0,
        failure_threshold: int = 3,
        quarantine_s: float = 30.0,
        recovery_probes: int = 2,
    ):
        self._lock = threading.Lock()
        self._backends: Dict[str, BackendHealth] = {}
        self.failure_window_s = failure_window_s
        self.failure_threshold = failure_threshold
        self.quarantine_s = quarantine_s
        self.recovery_probes = recovery_probes

    # ---- internal helpers -------------------------------------------------

    def _ensure(self, backend: str) -> BackendHealth:
        """Get or create health record (caller holds lock)."""
        if backend not in self._backends:
            self._backends[backend] = BackendHealth(backend=backend)
        return self._backends[backend]

    def _gc_failures(self, bh: BackendHealth, now: float) -> None:
        """Remove failures older than the rolling window (caller holds lock)."""
        cutoff = now - self.failure_window_s
        bh.failures = [f for f in bh.failures if f.timestamp >= cutoff]

    # ---- public API -------------------------------------------------------

    def record_success(self, backend: str) -> None:
        """Record a successful interaction with *backend*."""
        now = time.monotonic()
        with self._lock:
            bh = self._ensure(backend)
            bh.total_successes += 1
            bh.consecutive_successes += 1
            bh.last_check = now
            self._gc_failures(bh, now)

            if bh.state in (BackendState.QUARANTINED, BackendState.DEGRADED):
                if bh.consecutive_successes >= self.recovery_probes:
                    bh.state = BackendState.HEALTHY
                    bh.quarantine_until = 0.0
                    logger.info("health: %s recovered after %d probes",
                                backend, bh.consecutive_successes)
            else:
                bh.state = BackendState.HEALTHY

    def record_failure(self, backend: str, error: str = "") -> None:
        """Record a failure for *backend*.  May trigger quarantine."""
        now = time.monotonic()
        with self._lock:
            bh = self._ensure(backend)
            bh.total_failures += 1
            bh.consecutive_successes = 0
            bh.last_check = now
            bh.failures.append(FailureRecord(timestamp=now, error=error))
            self._gc_failures(bh, now)

            if len(bh.failures) >= self.failure_threshold:
                bh.state = BackendState.QUARANTINED
                bh.quarantine_until = now + self.quarantine_s
                logger.warning("health: %s quarantined for %.0fs (%d failures in %.0fs)",
                               backend, self.quarantine_s,
                               len(bh.failures), self.failure_window_s)

    def is_healthy(self, backend: str) -> bool:
        """
        Check whether *backend* is healthy enough to receive traffic.

        Returns True for HEALTHY, UNKNOWN, DEGRADED.
        Returns False for QUARANTINED (unless quarantine has expired).
        """
        now = time.monotonic()
        with self._lock:
            bh = self._ensure(backend)

            if bh.state != BackendState.QUARANTINED:
                return True

            # Quarantine expired -> allow probe traffic
            if now >= bh.quarantine_until:
                bh.state = BackendState.DEGRADED
                logger.info("health: %s quarantine expired, allowing probes", backend)
                return True

            return False

    # ---- queries ----------------------------------------------------------

    def get_state(self, backend: str) -> BackendState:
        with self._lock:
            return self._ensure(backend).state

    def quarantined_backends(self) -> List[str]:
        now = time.monotonic()
        with self._lock:
            return [
                b for b, bh in self._backends.items()
                if bh.state == BackendState.QUARANTINED and now < bh.quarantine_until
            ]

    def all_health(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {b: bh.to_dict() for b, bh in self._backends.items()}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backends": self.all_health(),
            "quarantined": self.quarantined_backends(),
            "config": {
                "failure_window_s": self.failure_window_s,
                "failure_threshold": self.failure_threshold,
                "quarantine_s": self.quarantine_s,
                "recovery_probes": self.recovery_probes,
            },
        }
