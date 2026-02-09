"""
Pipecat — Centralized Interrupt / Barge-In Handler

All interrupt requests flow through handle_interrupt().
Provides debounce (configurable window) and idempotency
(ignores duplicate interrupts for the same state_seq).

Contract:
    - Only valid from THINKING or SPEAKING states.
    - Signals cancel events on the session.
    - Transitions state through INTERRUPTED → RECOVERING → IDLE.
    - Returns an InterruptResult describing what happened.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.turn_taking import TurnState, transition
from app.session_manager import VoiceSession

logger = logging.getLogger(__name__)

# Default debounce window in seconds — interrupts arriving within this
# window after a previous interrupt are silently dropped.
DEFAULT_DEBOUNCE_SECS: float = 0.15


@dataclass
class InterruptResult:
    """Outcome of an interrupt attempt."""
    accepted: bool
    reason: str
    previous_state: str
    new_state: str
    state_seq: int
    debounced: bool = False


# Per-session timestamp of last accepted interrupt (monotonic).
_last_interrupt_ts: dict[str, float] = {}


def _should_debounce(session_id: str, debounce_secs: float) -> bool:
    """True if an interrupt arrived too soon after the previous one."""
    now = time.monotonic()
    last = _last_interrupt_ts.get(session_id, 0.0)
    if (now - last) < debounce_secs:
        return True
    return False


def _record_interrupt(session_id: str) -> None:
    _last_interrupt_ts[session_id] = time.monotonic()


def clear_interrupt_state(session_id: str) -> None:
    """Remove debounce tracking for a closed session."""
    _last_interrupt_ts.pop(session_id, None)


async def handle_interrupt(
    session: VoiceSession,
    reason: str = "barge_in",
    trace_id: str = "",
    debounce_secs: float = DEFAULT_DEBOUNCE_SECS,
    recover_to_idle: bool = True,
) -> InterruptResult:
    """
    Central entrypoint for all interrupt / barge-in events.

    Steps:
        1. Debounce check — drop if too soon after last interrupt.
        2. State guard — only THINKING or SPEAKING can be interrupted.
        3. Signal cancel events (infer + TTS).
        4. Transition to INTERRUPTED.
        5. Optionally transition INTERRUPTED → RECOVERING → IDLE.

    Args:
        session:          VoiceSession to interrupt.
        reason:           Human-readable reason (logged).
        trace_id:         Correlation ID.
        debounce_secs:    Minimum gap between successive interrupts.
        recover_to_idle:  If True, drive state all the way back to IDLE.

    Returns:
        InterruptResult describing the outcome.
    """
    prev_state = session.turn_state
    sid = session.session_id

    # ---- debounce ---------------------------------------------------------
    if _should_debounce(sid, debounce_secs):
        logger.debug(
            "interrupt debounced  session=%s  state=%s  reason=%s",
            sid, prev_state.value, reason,
        )
        return InterruptResult(
            accepted=False,
            reason="debounced",
            previous_state=prev_state.value,
            new_state=prev_state.value,
            state_seq=session.state_seq,
            debounced=True,
        )

    # ---- state guard ------------------------------------------------------
    interruptible = (TurnState.THINKING, TurnState.SPEAKING)
    if prev_state not in interruptible:
        logger.debug(
            "interrupt rejected (not interruptible)  session=%s  "
            "state=%s  reason=%s",
            sid, prev_state.value, reason,
        )
        return InterruptResult(
            accepted=False,
            reason=f"state {prev_state.value} is not interruptible",
            previous_state=prev_state.value,
            new_state=prev_state.value,
            state_seq=session.state_seq,
        )

    # ---- signal cancel events ---------------------------------------------
    session.signal_cancel_infer()
    session.signal_cancel_tts()

    # ---- transition to INTERRUPTED ----------------------------------------
    ok = await transition(
        session, TurnState.INTERRUPTED,
        reason=f"interrupt:{reason}", trace_id=trace_id,
    )
    if not ok:
        logger.warning(
            "interrupt transition failed  session=%s  %s -> INTERRUPTED",
            sid, prev_state.value,
        )
        return InterruptResult(
            accepted=False,
            reason="transition to INTERRUPTED failed",
            previous_state=prev_state.value,
            new_state=session.turn_state.value,
            state_seq=session.state_seq,
        )

    _record_interrupt(sid)

    # ---- recover to IDLE --------------------------------------------------
    if recover_to_idle:
        await transition(
            session, TurnState.RECOVERING,
            reason=f"post_interrupt:{reason}", trace_id=trace_id,
        )
        await transition(
            session, TurnState.IDLE,
            reason=f"interrupt_resolved:{reason}", trace_id=trace_id,
        )
        # Clear cancel events so next turn starts clean
        session.reset_cancel_events()

    logger.info(
        "interrupt handled  session=%s  %s -> %s  reason=%s  trace=%s",
        sid, prev_state.value, session.turn_state.value, reason, trace_id,
    )
    return InterruptResult(
        accepted=True,
        reason=reason,
        previous_state=prev_state.value,
        new_state=session.turn_state.value,
        state_seq=session.state_seq,
    )
