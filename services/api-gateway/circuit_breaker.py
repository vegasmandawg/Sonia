"""
Stage 5 M2 — Circuit Breaker
Per-dependency circuit breaker with three states: CLOSED → OPEN → HALF_OPEN.
Prevents cascading failures by short-circuiting calls to unhealthy deps.
"""

import asyncio
import time
import random
from typing import Any, Callable, Dict, Optional
from enum import Enum
from dataclasses import dataclass, field


class BreakerState(str, Enum):
    CLOSED = "closed"         # Normal operation, requests flow through
    OPEN = "open"             # Failing, requests short-circuited
    HALF_OPEN = "half_open"   # Probing with single request to check recovery


@dataclass
class BreakerConfig:
    """Configuration for a circuit breaker."""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout_s: float = 30.0    # Seconds to wait before half-open probe
    half_open_max_calls: int = 1        # Calls allowed in half-open state
    success_threshold: int = 2          # Successes in half-open before closing
    max_jitter_s: float = 5.0           # Random jitter added to recovery timeout


@dataclass
class BreakerStats:
    """Runtime statistics for a circuit breaker."""
    total_calls: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_short_circuits: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    last_state_change_time: Optional[float] = None
    trips: int = 0  # Number of times breaker opened


class CircuitBreaker:
    """
    Circuit breaker for a single dependency.
    Thread-safe via asyncio lock.
    """

    def __init__(self, name: str, config: BreakerConfig = None):
        self.name = name
        self.config = config or BreakerConfig()
        self.state = BreakerState.CLOSED
        self.stats = BreakerStats()
        self._lock = asyncio.Lock()
        self._half_open_calls = 0

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function through the circuit breaker.
        Raises CircuitOpenError if breaker is open.
        """
        async with self._lock:
            now = time.time()
            self.stats.total_calls += 1

            if self.state == BreakerState.OPEN:
                # Check if recovery timeout has elapsed
                elapsed = now - (self.stats.last_failure_time or 0)
                jitter = random.uniform(0, self.config.max_jitter_s)
                if elapsed >= self.config.recovery_timeout_s + jitter:
                    self.state = BreakerState.HALF_OPEN
                    self._half_open_calls = 0
                    self.stats.last_state_change_time = now
                else:
                    self.stats.total_short_circuits += 1
                    raise CircuitOpenError(
                        self.name,
                        f"Circuit breaker '{self.name}' is OPEN "
                        f"({self.stats.consecutive_failures} consecutive failures)"
                    )

            if self.state == BreakerState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    self.stats.total_short_circuits += 1
                    raise CircuitOpenError(
                        self.name,
                        f"Circuit breaker '{self.name}' is HALF_OPEN, max probe calls reached"
                    )
                self._half_open_calls += 1

        # Execute outside the lock
        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except Exception as e:
            await self._record_failure()
            raise

    async def _record_success(self):
        async with self._lock:
            now = time.time()
            self.stats.total_successes += 1
            self.stats.consecutive_successes += 1
            self.stats.consecutive_failures = 0
            self.stats.last_success_time = now

            if self.state == BreakerState.HALF_OPEN:
                if self.stats.consecutive_successes >= self.config.success_threshold:
                    self.state = BreakerState.CLOSED
                    self.stats.last_state_change_time = now

    async def _record_failure(self):
        async with self._lock:
            now = time.time()
            self.stats.total_failures += 1
            self.stats.consecutive_failures += 1
            self.stats.consecutive_successes = 0
            self.stats.last_failure_time = now

            if self.state == BreakerState.HALF_OPEN:
                # Any failure in half-open trips back to open
                self.state = BreakerState.OPEN
                self.stats.trips += 1
                self.stats.last_state_change_time = now

            elif self.state == BreakerState.CLOSED:
                if self.stats.consecutive_failures >= self.config.failure_threshold:
                    self.state = BreakerState.OPEN
                    self.stats.trips += 1
                    self.stats.last_state_change_time = now

    async def reset(self):
        """Manually reset breaker to CLOSED state."""
        async with self._lock:
            self.state = BreakerState.CLOSED
            self.stats.consecutive_failures = 0
            self.stats.consecutive_successes = 0
            self._half_open_calls = 0
            self.stats.last_state_change_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize breaker state for observability."""
        return {
            "name": self.name,
            "state": self.state.value,
            "stats": {
                "total_calls": self.stats.total_calls,
                "total_successes": self.stats.total_successes,
                "total_failures": self.stats.total_failures,
                "total_short_circuits": self.stats.total_short_circuits,
                "consecutive_failures": self.stats.consecutive_failures,
                "consecutive_successes": self.stats.consecutive_successes,
                "trips": self.stats.trips,
            },
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout_s": self.config.recovery_timeout_s,
            },
        }


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open."""

    def __init__(self, breaker_name: str, message: str):
        self.breaker_name = breaker_name
        super().__init__(message)


# ── Breaker Registry ─────────────────────────────────────────────────────────

class BreakerRegistry:
    """
    Registry of circuit breakers, one per dependency.
    """

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}

    def get_or_create(self, name: str, config: BreakerConfig = None) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        return self._breakers.get(name)

    def all(self) -> Dict[str, CircuitBreaker]:
        return dict(self._breakers)

    def summary(self) -> Dict[str, Any]:
        return {
            name: cb.to_dict() for name, cb in self._breakers.items()
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_registry: Optional[BreakerRegistry] = None


def get_breaker_registry() -> BreakerRegistry:
    global _registry
    if _registry is None:
        _registry = BreakerRegistry()
    return _registry
