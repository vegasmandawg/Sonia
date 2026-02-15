"""Retry and circuit breaker support for OpenClaw tool execution.

Provides execution-level retry with exponential backoff and
a lightweight circuit breaker for individual tool backends.
"""

import time
import logging
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("openclaw.retry")


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RetryPolicy:
    """Retry configuration for tool execution."""
    max_retries: int = 2
    base_delay_s: float = 0.5
    max_delay_s: float = 5.0
    backoff_factor: float = 2.0
    retryable_errors: tuple = (TimeoutError, ConnectionError, OSError)


@dataclass
class CircuitBreaker:
    """Per-tool circuit breaker."""
    name: str
    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0

    _state: BreakerState = field(default=BreakerState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _success_count: int = field(default=0, init=False)

    @property
    def state(self) -> BreakerState:
        if self._state == BreakerState.OPEN:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout_s:
                self._state = BreakerState.HALF_OPEN
                self._success_count = 0
        return self._state

    def record_success(self):
        if self._state == BreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= 2:
                self._state = BreakerState.CLOSED
                self._failure_count = 0
                logger.info("Breaker %s: CLOSED (recovered)", self.name)
        elif self._state == BreakerState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == BreakerState.HALF_OPEN:
            self._state = BreakerState.OPEN
            logger.warning("Breaker %s: OPEN (half-open probe failed)", self.name)
        elif self._failure_count >= self.failure_threshold:
            self._state = BreakerState.OPEN
            logger.warning("Breaker %s: OPEN (threshold %d reached)", self.name, self.failure_threshold)

    @property
    def allows_request(self) -> bool:
        return self.state != BreakerState.OPEN

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
        }


class ToolRetryExecutor:
    """Execute tool calls with retry and circuit breaker logic."""

    def __init__(self, policy: Optional[RetryPolicy] = None):
        self.policy = policy or RetryPolicy()
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_breaker(self, tool_name: str) -> CircuitBreaker:
        if tool_name not in self._breakers:
            self._breakers[tool_name] = CircuitBreaker(name=tool_name)
        return self._breakers[tool_name]

    def execute_with_retry(self, tool_name: str, fn: Callable, *args, **kwargs) -> Any:
        """Execute a tool function with retry and circuit breaker."""
        breaker = self.get_breaker(tool_name)

        if not breaker.allows_request:
            return {
                "status": "circuit_open",
                "tool_name": tool_name,
                "message": f"Circuit breaker open for {tool_name}",
            }

        last_error = None
        for attempt in range(self.policy.max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                breaker.record_success()
                return result
            except self.policy.retryable_errors as e:
                last_error = e
                breaker.record_failure()
                if attempt < self.policy.max_retries:
                    delay = min(
                        self.policy.base_delay_s * (self.policy.backoff_factor ** attempt),
                        self.policy.max_delay_s,
                    )
                    logger.warning(
                        "Tool %s attempt %d failed: %s, retrying in %.1fs",
                        tool_name, attempt + 1, e, delay,
                    )
                    time.sleep(delay)
            except Exception as e:
                breaker.record_failure()
                raise

        return {
            "status": "retry_exhausted",
            "tool_name": tool_name,
            "message": f"All {self.policy.max_retries + 1} attempts failed: {last_error}",
        }

    def all_breaker_status(self) -> list[dict]:
        return [b.to_dict() for b in self._breakers.values()]
