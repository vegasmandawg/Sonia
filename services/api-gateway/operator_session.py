"""
v2.8 M4: Operator Session -- UX State Machine

Provides operator-facing UX primitives:
  - Push-to-talk state machine (idle -> listening -> processing -> responding)
  - Real-time state indicators for all subsystems
  - Incident snapshot export for debugging
  - Session activity timeline

Architecture:
  The OperatorSession wraps a gateway session with UX-specific state:
  - InputMode: push_to_talk / always_on / text_only
  - TalkState: IDLE / LISTENING / PROCESSING / RESPONDING
  - SubsystemStatus: one per subsystem (model, memory, perception, action)
  - ActivityLog: bounded timeline of operator-visible events

Usage:
    op = OperatorSession(session_id="sess_1")
    op.begin_listening()   # TalkState -> LISTENING
    op.begin_processing()  # TalkState -> PROCESSING
    op.begin_responding()  # TalkState -> RESPONDING
    op.end_turn()          # TalkState -> IDLE

    indicators = op.get_indicators()
    snapshot = op.export_incident_snapshot()
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TalkState(str, Enum):
    """Push-to-talk state machine."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"


class InputMode(str, Enum):
    """Operator input mode."""
    PUSH_TO_TALK = "push_to_talk"
    ALWAYS_ON = "always_on"
    TEXT_ONLY = "text_only"


class SubsystemHealth(str, Enum):
    """Health status for a subsystem."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


# Valid state transitions for push-to-talk
VALID_TRANSITIONS = {
    TalkState.IDLE: {TalkState.LISTENING},
    TalkState.LISTENING: {TalkState.PROCESSING, TalkState.IDLE},  # Can cancel
    TalkState.PROCESSING: {TalkState.RESPONDING, TalkState.IDLE},  # Can cancel
    TalkState.RESPONDING: {TalkState.IDLE, TalkState.LISTENING},  # Barge-in
}


@dataclass
class SubsystemStatus:
    """Status of a single subsystem."""
    name: str = ""
    health: SubsystemHealth = SubsystemHealth.UNKNOWN
    latency_ms: float = 0.0
    last_check: float = 0.0
    detail: str = ""
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "health": self.health.value,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check,
            "detail": self.detail,
            "error_count": self.error_count,
        }


@dataclass
class ActivityEntry:
    """A single entry in the operator activity timeline."""
    timestamp: float = 0.0
    event_type: str = ""
    detail: str = ""
    turn_id: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "detail": self.detail,
            "turn_id": self.turn_id,
            "duration_ms": self.duration_ms,
        }


class InvalidStateTransition(RuntimeError):
    """Raised when a state transition is not valid."""
    def __init__(self, from_state: TalkState, to_state: TalkState):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid transition: {from_state.value} -> {to_state.value}")


class OperatorSession:
    """
    Operator-facing session with UX state management.

    Tracks:
      - Push-to-talk state machine
      - Input mode configuration
      - Subsystem health indicators
      - Activity timeline
      - Turn latency metrics
    """

    MAX_ACTIVITY = 200

    def __init__(
        self,
        session_id: str,
        input_mode: InputMode = InputMode.PUSH_TO_TALK,
    ):
        self.session_id = session_id
        self.input_mode = input_mode
        self._talk_state = TalkState.IDLE
        self._created_at = time.time()
        self._current_turn_id: Optional[str] = None
        self._turn_start: Optional[float] = None

        # Subsystem indicators
        self._subsystems: Dict[str, SubsystemStatus] = {
            "model": SubsystemStatus(name="model"),
            "memory": SubsystemStatus(name="memory"),
            "perception": SubsystemStatus(name="perception"),
            "action": SubsystemStatus(name="action"),
            "gateway": SubsystemStatus(name="gateway"),
        }

        # Activity timeline
        self._activity: List[ActivityEntry] = []

        # Metrics
        self._total_turns = 0
        self._total_cancels = 0
        self._total_errors = 0
        self._turn_latencies: List[float] = []

    @property
    def talk_state(self) -> TalkState:
        return self._talk_state

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._created_at

    @property
    def current_turn_id(self) -> Optional[str]:
        return self._current_turn_id

    # ── State transitions ────────────────────────────────────────────────

    def _transition(self, to_state: TalkState):
        """Validate and execute state transition."""
        if to_state not in VALID_TRANSITIONS.get(self._talk_state, set()):
            raise InvalidStateTransition(self._talk_state, to_state)
        old = self._talk_state
        self._talk_state = to_state
        self._log_activity(
            f"state.{to_state.value}",
            f"Transition {old.value} -> {to_state.value}",
        )

    def begin_listening(self) -> str:
        """Start listening for user input. Returns turn_id."""
        self._transition(TalkState.LISTENING)
        self._current_turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        self._turn_start = time.monotonic()
        return self._current_turn_id

    def begin_processing(self):
        """User finished speaking, begin processing."""
        self._transition(TalkState.PROCESSING)

    def begin_responding(self):
        """Model response ready, begin playback."""
        self._transition(TalkState.RESPONDING)

    def end_turn(self, ok: bool = True, error: str = ""):
        """Turn completed, return to idle."""
        if self._talk_state == TalkState.IDLE:
            return  # Already idle

        # Calculate turn duration
        duration_ms = 0.0
        if self._turn_start:
            duration_ms = (time.monotonic() - self._turn_start) * 1000

        self._talk_state = TalkState.IDLE
        self._total_turns += 1

        if ok:
            self._turn_latencies.append(duration_ms)
        else:
            self._total_errors += 1

        self._log_activity(
            "turn.completed" if ok else "turn.error",
            error if error else f"Turn completed in {duration_ms:.0f}ms",
            turn_id=self._current_turn_id or "",
            duration_ms=duration_ms,
        )

        self._current_turn_id = None
        self._turn_start = None

    def cancel_turn(self, reason: str = "user_cancel"):
        """Cancel the current turn."""
        if self._talk_state == TalkState.IDLE:
            return

        self._total_cancels += 1
        self._log_activity(
            "turn.cancelled",
            f"Cancelled: {reason}",
            turn_id=self._current_turn_id or "",
        )
        self._talk_state = TalkState.IDLE
        self._current_turn_id = None
        self._turn_start = None

    # ── Subsystem indicators ────────────────────────────────────────────

    def update_subsystem(
        self,
        name: str,
        health: SubsystemHealth,
        latency_ms: float = 0.0,
        detail: str = "",
    ):
        """Update a subsystem's health indicator."""
        if name not in self._subsystems:
            self._subsystems[name] = SubsystemStatus(name=name)
        ss = self._subsystems[name]
        ss.health = health
        ss.latency_ms = latency_ms
        ss.last_check = time.time()
        ss.detail = detail
        if health == SubsystemHealth.DOWN:
            ss.error_count += 1

    def get_indicators(self) -> Dict[str, Any]:
        """Return all UX state indicators for the operator."""
        return {
            "session_id": self.session_id,
            "talk_state": self._talk_state.value,
            "input_mode": self.input_mode.value,
            "current_turn_id": self._current_turn_id,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "subsystems": {
                name: ss.to_dict()
                for name, ss in self._subsystems.items()
            },
            "metrics": {
                "total_turns": self._total_turns,
                "total_cancels": self._total_cancels,
                "total_errors": self._total_errors,
                "avg_latency_ms": (
                    sum(self._turn_latencies[-20:]) / len(self._turn_latencies[-20:])
                    if self._turn_latencies else 0.0
                ),
            },
        }

    # ── Activity timeline ───────────────────────────────────────────────

    def _log_activity(
        self,
        event_type: str,
        detail: str,
        turn_id: str = "",
        duration_ms: float = 0.0,
    ):
        entry = ActivityEntry(
            timestamp=time.time(),
            event_type=event_type,
            detail=detail,
            turn_id=turn_id or self._current_turn_id or "",
            duration_ms=duration_ms,
        )
        self._activity.append(entry)
        if len(self._activity) > self.MAX_ACTIVITY:
            self._activity = self._activity[-self.MAX_ACTIVITY:]

    def get_activity(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return recent activity entries."""
        return [e.to_dict() for e in self._activity[-limit:]]

    # ── Incident snapshot ───────────────────────────────────────────────

    def export_incident_snapshot(self) -> Dict[str, Any]:
        """
        Export a full incident snapshot for debugging.

        Includes: state, indicators, recent activity, metrics.
        """
        return {
            "snapshot_id": f"snap_{uuid.uuid4().hex[:12]}",
            "timestamp": time.time(),
            "session_id": self.session_id,
            "talk_state": self._talk_state.value,
            "input_mode": self.input_mode.value,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "indicators": self.get_indicators(),
            "recent_activity": self.get_activity(limit=50),
            "metrics": {
                "total_turns": self._total_turns,
                "total_cancels": self._total_cancels,
                "total_errors": self._total_errors,
                "turn_latencies_last_20": self._turn_latencies[-20:],
            },
        }

    # ── Input mode management ────────────────────────────────────────────

    def set_input_mode(self, mode: InputMode):
        """Change the operator's input mode."""
        old = self.input_mode
        self.input_mode = mode
        self._log_activity(
            "mode.changed",
            f"Input mode: {old.value} -> {mode.value}",
        )
