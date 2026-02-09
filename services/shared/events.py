"""
Unified Event Envelope -- v2.6 Cross-Track Integration

Shared event contract used by all services:
  - vision-capture (7060): emits vision.frame.available
  - perception (7070): consumes vision events, emits perception.completed
  - api-gateway (7000): routes events to WS clients, emits session events

Every event has:
  - id: UUID
  - timestamp: epoch float
  - type: EventType enum value
  - source: service name
  - correlation_id: propagated across service boundaries
  - payload: arbitrary dict

Correlation ID rules:
  1. If inbound event has a correlation_id, propagate it.
  2. If no correlation_id, generate one (req_XXXX format).
  3. All downstream events and logs must carry the same correlation_id.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Event types (cross-service)
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    # Vision capture
    FRAME_AVAILABLE = "vision.frame.available"
    PRIVACY_CHANGED = "vision.privacy.changed"
    MODE_CHANGED = "vision.mode.changed"

    # Perception
    PERCEPTION_REQUESTED = "perception.requested"
    PERCEPTION_COMPLETED = "perception.completed"
    PERCEPTION_FAILED = "perception.failed"

    # Session
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"

    # Turn
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"

    # Control (UI -> backend)
    CONTROL_TOGGLE = "control.toggle"
    CONTROL_INTERRUPT = "control.interrupt"
    CONTROL_REPLAY = "control.replay"
    CONTROL_HOLD = "control.hold"

    # Acknowledgments (backend -> UI)
    ACK_CONTROL = "ack.control"
    NACK_CONTROL = "nack.control"
    ACK_INTERRUPT = "ack.interrupt"
    ACK_REPLAY = "ack.replay"

    # Diagnostics
    DIAGNOSTICS_SNAPSHOT = "diagnostics.snapshot"


# ---------------------------------------------------------------------------
# Correlation ID generation
# ---------------------------------------------------------------------------

def generate_correlation_id() -> str:
    """Generate a correlation ID in the standard req_XXXX format."""
    return f"req_{uuid.uuid4().hex[:12]}"


def ensure_correlation_id(existing: Optional[str]) -> str:
    """Return existing ID if non-empty, else generate one."""
    if existing and existing.strip():
        return existing
    return generate_correlation_id()


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------

class EventEnvelope(BaseModel):
    """Unified event envelope for cross-service communication."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    type: str  # EventType value or custom string
    source: str = ""
    correlation_id: str = Field(default_factory=generate_correlation_id)
    payload: Dict[str, Any] = Field(default_factory=dict)

    def derive(
        self,
        event_type: str,
        source: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> "EventEnvelope":
        """Create a child event preserving correlation_id."""
        return EventEnvelope(
            type=event_type,
            source=source,
            correlation_id=self.correlation_id,
            payload=payload or {},
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_envelope(data: dict) -> tuple[bool, str]:
    """Validate a raw dict as an EventEnvelope. Returns (valid, error_msg)."""
    if not isinstance(data, dict):
        return False, "envelope must be a dict"
    if "type" not in data:
        return False, "missing required field: type"
    if "correlation_id" not in data or not data["correlation_id"]:
        return False, "missing or empty correlation_id"
    return True, ""
