"""Turn state model for voice turn lifecycle.

TurnState is the finite set of states a voice turn can be in.
TurnSnapshot is the immutable state record produced by the reducer.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TurnState(str, Enum):
    """Voice turn lifecycle states."""
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTING = "INTERRUPTING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    ERROR = "ERROR"


# Terminal states -- a turn can produce at most one terminal state.
TERMINAL_STATES: frozenset[TurnState] = frozenset([
    TurnState.COMPLETED,
    TurnState.ABORTED,
    TurnState.ERROR,
])


@dataclass(frozen=True)
class TurnSnapshot:
    """Immutable snapshot of turn state at a given sequence point.

    All fields are deterministic (no wall-clock). This enables replay
    verification via deterministic_hash().
    """
    session_id: str
    turn_id: str
    state: TurnState
    seq: int
    correlation_id: str
    model_stream_active: bool = False
    tts_active: bool = False
    cancel_requested: bool = False
    terminal: bool = False
    reason: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def deterministic_hash(self) -> str:
        """Hash only deterministic fields for replay verification (G19).

        Excludes wall-clock/non-deterministic data. Includes:
        state, seq, terminal, reason, cancellation flags, and identity.
        """
        fields = {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "state": self.state.value,
            "seq": self.seq,
            "model_stream_active": self.model_stream_active,
            "tts_active": self.tts_active,
            "cancel_requested": self.cancel_requested,
            "terminal": self.terminal,
            "reason": self.reason,
        }
        canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def evolve(self, **kwargs) -> TurnSnapshot:
        """Create a new snapshot with updated fields."""
        current = {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "state": self.state,
            "seq": self.seq,
            "correlation_id": self.correlation_id,
            "model_stream_active": self.model_stream_active,
            "tts_active": self.tts_active,
            "cancel_requested": self.cancel_requested,
            "terminal": self.terminal,
            "reason": self.reason,
        }
        current.update(kwargs)
        return TurnSnapshot(**current)


def make_initial_snapshot(session_id: str, turn_id: str, correlation_id: str) -> TurnSnapshot:
    """Create the initial IDLE snapshot for a new turn."""
    return TurnSnapshot(
        session_id=session_id,
        turn_id=turn_id,
        state=TurnState.IDLE,
        seq=0,
        correlation_id=correlation_id,
    )
