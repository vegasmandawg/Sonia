"""Simple in-memory rate limiter for SONIA services.

Token bucket algorithm with per-client tracking.
"""

import time
import threading
from collections import defaultdict
from typing import Tuple


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, burst: int):
        """
        Args:
            rate: Tokens added per second
            burst: Maximum tokens (burst capacity)
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """Try to consume tokens.

        Returns:
            (allowed, retry_after_seconds)
        """
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True, 0.0
            else:
                wait = (tokens - self._tokens) / self.rate
                return False, wait


class RateLimiter:
    """Per-client rate limiter using token buckets."""

    def __init__(self, rate: float = 10.0, burst: int = 20, cleanup_interval: int = 300):
        """
        Args:
            rate: Requests per second per client
            burst: Maximum burst size per client
            cleanup_interval: Seconds between cleanup of stale buckets
        """
        self.rate = rate
        self.burst = burst
        self._buckets: dict = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = cleanup_interval

    def check(self, client_id: str = "default") -> Tuple[bool, float]:
        """Check if request is allowed for client.

        Returns:
            (allowed, retry_after_seconds)
        """
        with self._lock:
            # Periodic cleanup
            now = time.monotonic()
            if now - self._last_cleanup > self._cleanup_interval:
                self._cleanup()
                self._last_cleanup = now

            if client_id not in self._buckets:
                self._buckets[client_id] = TokenBucket(self.rate, self.burst)

        return self._buckets[client_id].consume()

    def _cleanup(self):
        """Remove stale buckets (full buckets = inactive clients)."""
        stale = [k for k, v in self._buckets.items() if v._tokens >= v.burst]
        for k in stale:
            del self._buckets[k]
