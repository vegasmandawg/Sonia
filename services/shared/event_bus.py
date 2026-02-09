"""
Event Bus -- v2.7-m2

In-process async event bus for inter-service communication.
Dispatches EventEnvelopes to registered handlers with:

  - Topic-based routing (subscribe by EventType pattern)
  - Async handler execution with timeout
  - Dead letter queue for failed deliveries
  - Correlation ID propagation
  - Bounded event history for diagnostics
  - HTTP bridge mode for cross-process events

Usage:
    bus = EventBus()
    bus.subscribe("vision.frame.available", on_frame)
    bus.subscribe("perception.*", on_any_perception)
    await bus.publish(EventEnvelope(type="vision.frame.available", ...))

HTTP bridge (for cross-process dispatch):
    bridge = HttpEventBridge(bus)
    bridge.register_target("perception", "http://127.0.0.1:7070/v1/perception/events")
    # Events matching "perception.*" are POSTed to the target URL
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger("sonia.event_bus")


@dataclass
class EventRecord:
    """Lightweight record for event history."""
    event_id: str
    event_type: str
    source: str
    correlation_id: str
    timestamp: float
    delivered_to: int = 0
    failed: int = 0
    latency_ms: float = 0.0


@dataclass
class DeadLetter:
    """Failed event delivery."""
    event_id: str
    event_type: str
    handler_name: str
    error: str
    timestamp: float
    correlation_id: str


Handler = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """
    Async in-process event bus with pattern matching.

    Supports glob patterns for topic subscriptions:
      - "vision.*" matches "vision.frame.available", "vision.privacy.changed"
      - "perception.completed" matches exactly
      - "*" matches everything
    """

    HANDLER_TIMEOUT_S = 10.0
    MAX_HISTORY = 500
    MAX_DEAD_LETTERS = 100

    def __init__(self, name: str = "default"):
        self.name = name
        self._subscriptions: List[_Subscription] = []
        self._history: List[EventRecord] = []
        self._dead_letters: List[DeadLetter] = []
        self._total_published: int = 0
        self._total_delivered: int = 0
        self._total_failed: int = 0
        self._started_at: float = time.time()

    def subscribe(
        self,
        pattern: str,
        handler: Handler,
        name: str = "",
    ) -> str:
        """Subscribe a handler to events matching pattern. Returns subscription ID."""
        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        sub = _Subscription(
            id=sub_id,
            pattern=pattern,
            handler=handler,
            name=name or handler.__name__,
        )
        self._subscriptions.append(sub)
        logger.info("Subscribed %s to '%s' (id=%s)", sub.name, pattern, sub_id)
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """Remove a subscription by ID."""
        before = len(self._subscriptions)
        self._subscriptions = [s for s in self._subscriptions if s.id != sub_id]
        return len(self._subscriptions) < before

    async def publish(self, event: Dict[str, Any]) -> int:
        """
        Publish an event to all matching subscribers.
        Returns number of handlers that received the event.
        """
        event_type = event.get("type", "")
        event_id = event.get("id", str(uuid.uuid4()))
        source = event.get("source", "")
        correlation_id = event.get("correlation_id", "")

        self._total_published += 1
        t0 = time.monotonic()

        # Find matching subscriptions
        matching = [s for s in self._subscriptions if s.matches(event_type)]

        delivered = 0
        failed = 0

        for sub in matching:
            try:
                await asyncio.wait_for(
                    sub.handler(event),
                    timeout=self.HANDLER_TIMEOUT_S,
                )
                delivered += 1
                self._total_delivered += 1
            except asyncio.TimeoutError:
                failed += 1
                self._total_failed += 1
                self._record_dead_letter(event_id, event_type, sub.name, "timeout", correlation_id)
                logger.warning("Handler %s timed out for %s", sub.name, event_type)
            except Exception as e:
                failed += 1
                self._total_failed += 1
                self._record_dead_letter(event_id, event_type, sub.name, str(e), correlation_id)
                logger.warning("Handler %s failed for %s: %s", sub.name, event_type, e)

        elapsed = (time.monotonic() - t0) * 1000

        # Record history
        record = EventRecord(
            event_id=event_id,
            event_type=event_type,
            source=source,
            correlation_id=correlation_id,
            timestamp=time.time(),
            delivered_to=delivered,
            failed=failed,
            latency_ms=round(elapsed, 1),
        )
        self._history.append(record)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]

        logger.debug(
            "Published %s: %d delivered, %d failed (%.1fms)",
            event_type, delivered, failed, elapsed,
        )

        return delivered

    def get_stats(self) -> Dict[str, Any]:
        """Return bus statistics."""
        return {
            "name": self.name,
            "subscriptions": len(self._subscriptions),
            "total_published": self._total_published,
            "total_delivered": self._total_delivered,
            "total_failed": self._total_failed,
            "dead_letters": len(self._dead_letters),
            "history_size": len(self._history),
            "uptime_seconds": round(time.time() - self._started_at, 1),
        }

    def get_dead_letters(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent dead letters."""
        return [
            {
                "event_id": dl.event_id,
                "event_type": dl.event_type,
                "handler": dl.handler_name,
                "error": dl.error,
                "timestamp": dl.timestamp,
                "correlation_id": dl.correlation_id,
            }
            for dl in self._dead_letters[-limit:]
        ]

    def _record_dead_letter(
        self, event_id: str, event_type: str,
        handler_name: str, error: str, correlation_id: str,
    ) -> None:
        self._dead_letters.append(DeadLetter(
            event_id=event_id,
            event_type=event_type,
            handler_name=handler_name,
            error=error,
            timestamp=time.time(),
            correlation_id=correlation_id,
        ))
        if len(self._dead_letters) > self.MAX_DEAD_LETTERS:
            self._dead_letters = self._dead_letters[-self.MAX_DEAD_LETTERS:]


@dataclass
class _Subscription:
    id: str
    pattern: str
    handler: Handler
    name: str

    def matches(self, event_type: str) -> bool:
        return fnmatch.fnmatch(event_type, self.pattern)


# ---------------------------------------------------------------------------
# HTTP Event Bridge (cross-process dispatch)
# ---------------------------------------------------------------------------

class HttpEventBridge:
    """
    Bridges in-process events to remote services via HTTP POST.

    Subscribes to specified patterns on the bus, then forwards
    matching events as HTTP POST requests to target URLs.
    """

    def __init__(self, bus: EventBus, timeout: float = 5.0):
        self.bus = bus
        self.timeout = timeout
        self._targets: Dict[str, _BridgeTarget] = {}
        self._total_forwarded: int = 0
        self._total_forward_errors: int = 0

    def register_target(
        self,
        name: str,
        url: str,
        patterns: List[str],
    ) -> None:
        """Register a remote target that receives events matching patterns."""
        target = _BridgeTarget(name=name, url=url, patterns=patterns)
        self._targets[name] = target

        for pattern in patterns:
            self.bus.subscribe(
                pattern=pattern,
                handler=self._make_handler(target),
                name=f"bridge:{name}:{pattern}",
            )
        logger.info("Registered bridge target %s -> %s (%s)", name, url, patterns)

    async def _forward(self, target: _BridgeTarget, event: Dict[str, Any]) -> None:
        """POST event to remote target."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(target.url, json=event)
                resp.raise_for_status()
                self._total_forwarded += 1
        except Exception as e:
            self._total_forward_errors += 1
            logger.warning("Bridge forward to %s failed: %s", target.name, e)
            raise

    def _make_handler(self, target: _BridgeTarget) -> Handler:
        async def handler(event: Dict[str, Any]) -> None:
            await self._forward(target, event)
        handler.__name__ = f"bridge_{target.name}"
        return handler

    def get_stats(self) -> Dict[str, Any]:
        return {
            "targets": {
                name: {"url": t.url, "patterns": t.patterns}
                for name, t in self._targets.items()
            },
            "total_forwarded": self._total_forwarded,
            "total_errors": self._total_forward_errors,
        }


@dataclass
class _BridgeTarget:
    name: str
    url: str
    patterns: List[str]
