"""
Pipecat — Deterministic Turn State Machine

All voice-loop state transitions flow through transition().
No other module may write session.turn_state directly.

States:
    IDLE        — waiting for user speech
    LISTENING   — VAD has detected speech, buffering audio
    THINKING    — ASR complete, waiting for model inference
    SPEAKING    — TTS audio streaming to user
    INTERRUPTED — barge-in detected, cancelling current output
    RECOVERING  — cleanup in progress after error or interrupt

Invariants:
    1. Every transition is validated against ALLOWED_TRANSITIONS.
    2. A per-session asyncio.Lock serialises concurrent transition attempts.
    3. state_seq is monotonically incremented on every successful transition.
    4. turn_seq is incremented only on IDLE → LISTENING (new turn).
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Turn states
# ---------------------------------------------------------------------------

class TurnState(str, Enum):
    """Voice loop turn states."""
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    RECOVERING = "RECOVERING"


# ---------------------------------------------------------------------------
# Allowed transition matrix
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: Dict[TurnState, Tuple[TurnState, ...]] = {
    TurnState.IDLE:        (TurnState.LISTENING,),
    TurnState.LISTENING:   (TurnState.THINKING, TurnState.IDLE),
    TurnState.THINKING:    (TurnState.SPEAKING, TurnState.INTERRUPTED, TurnState.RECOVERING),
    TurnState.SPEAKING:    (TurnState.IDLE, TurnState.INTERRUPTED),
    TurnState.INTERRUPTED: (TurnState.RECOVERING, TurnState.IDLE),
    TurnState.RECOVERING:  (TurnState.IDLE,),
}


# Per-session locks — keyed by session_id so independent sessions
# never block each other.
_session_locks: Dict[str, asyncio.Lock] = {}


def _get_lock(session_id: str) -> asyncio.Lock:
    """Return (or create) the per-session transition lock."""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


def remove_lock(session_id: str) -> None:
    """Remove the per-session lock on session teardown."""
    _session_locks.pop(session_id, None)


# ---------------------------------------------------------------------------
# Core transition function
# ---------------------------------------------------------------------------

async def transition(
    session,  # VoiceSession (avoiding circular import)
    target: TurnState,
    reason: str = "",
    trace_id: str = "",
) -> bool:
    """
    Attempt a state transition for *session*.

    Returns True if the transition succeeded, False if it was rejected.
    On rejection the session state is unchanged.

    This is the **only** sanctioned way to change turn state.

    Args:
        session:   VoiceSession instance (must have .turn_state, .state_seq,
                   .turn_seq, .session_id, .last_state_change_ts attributes).
        target:    Desired next TurnState.
        reason:    Human-readable reason for the transition (logged).
        trace_id:  Correlation / trace ID for observability.
    """
    lock = _get_lock(session.session_id)

    async with lock:
        current = session.turn_state
        allowed = ALLOWED_TRANSITIONS.get(current, ())

        if target not in allowed:
            logger.warning(
                "transition REJECTED  session=%s  %s → %s  "
                "allowed=%s  reason=%s  trace=%s",
                session.session_id,
                current.value,
                target.value,
                [s.value for s in allowed],
                reason,
                trace_id,
            )
            return False

        # ---- apply --------------------------------------------------------
        prev = current
        session.turn_state = target
        session.state_seq += 1
        session.last_state_change_ts = time.monotonic()

        # New turn starts when we leave IDLE → LISTENING
        if prev == TurnState.IDLE and target == TurnState.LISTENING:
            session.turn_seq += 1

        logger.info(
            "transition OK  session=%s  %s → %s  "
            "state_seq=%d  turn_seq=%d  reason=%s  trace=%s",
            session.session_id,
            prev.value,
            target.value,
            session.state_seq,
            session.turn_seq,
            reason,
            trace_id,
        )
        return True


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_state_snapshot(session) -> dict:
    """
    Return a read-only snapshot of the session's turn-state metadata.

    Useful for health endpoints, telemetry, and diagnostics.
    """
    return {
        "session_id": session.session_id,
        "turn_state": session.turn_state.value,
        "state_seq": session.state_seq,
        "turn_seq": session.turn_seq,
        "last_state_change_ts": session.last_state_change_ts,
    }


def is_terminal_or_idle(state: TurnState) -> bool:
    """True when the state machine is at rest or in a terminal state."""
    return state in (TurnState.IDLE,)
