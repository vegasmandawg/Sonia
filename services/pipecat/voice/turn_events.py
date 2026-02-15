"""Typed event model for voice turn lifecycle.

Every event carries session_id, turn_id, seq, ts_monotonic_ns, correlation_id.
seq is strictly monotonic per (session_id, turn_id).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

EventType = Literal[
    "TURN_STARTED",
    "ASR_PARTIAL",
    "ASR_FINAL",
    "MODEL_FIRST_TOKEN",
    "MODEL_STREAM_ENDED",
    "TTS_STARTED",
    "TTS_CHUNK",
    "TTS_ENDED",
    "BARGE_IN_REQUESTED",
    "CANCEL_REQUESTED",
    "CANCEL_ACK",
    "TURN_TIMEOUT",
    "TURN_FAILED",
]

# All valid event type values for runtime validation
ALL_EVENT_TYPES: frozenset[str] = frozenset([
    "TURN_STARTED", "ASR_PARTIAL", "ASR_FINAL", "MODEL_FIRST_TOKEN",
    "MODEL_STREAM_ENDED", "TTS_STARTED", "TTS_CHUNK", "TTS_ENDED",
    "BARGE_IN_REQUESTED", "CANCEL_REQUESTED", "CANCEL_ACK",
    "TURN_TIMEOUT", "TURN_FAILED",
])


@dataclass(frozen=True)
class TurnEvent:
    """Immutable event in the voice turn lifecycle.

    Fields:
        event_type: One of the 13 defined event types.
        session_id: Session this event belongs to.
        turn_id: Turn within the session.
        seq: Strictly monotonic sequence number per (session_id, turn_id).
        ts_monotonic_ns: Monotonic nanosecond timestamp for ordering/latency.
        correlation_id: Correlation ID for distributed tracing.
        payload: Optional event-specific data (e.g., ASR text, error info).
    """
    event_type: EventType
    session_id: str
    turn_id: str
    seq: int
    ts_monotonic_ns: int
    correlation_id: str
    payload: Optional[dict] = None

    def __post_init__(self):
        if self.event_type not in ALL_EVENT_TYPES:
            raise ValueError(f"Unknown event type: {self.event_type}")
        if self.seq < 0:
            raise ValueError(f"seq must be non-negative, got {self.seq}")
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if not self.turn_id:
            raise ValueError("turn_id must be non-empty")
        if not self.correlation_id:
            raise ValueError("correlation_id must be non-empty")
