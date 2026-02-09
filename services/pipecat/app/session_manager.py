"""
Pipecat — Voice Session Manager (Hardened)

Extends the base session concept with:
    - trace_id / turn_id per session
    - asyncio cancel events (cancel_infer_evt, cancel_tts_evt)
    - last_user_audio_ts, last_state_change_ts timestamps
    - active_tasks registry with cleanup-with-timeout on close
    - strict IDLE reset after any recoverable failure

This module owns VoiceSession lifecycle.  Turn-state writes are delegated
to app.turn_taking.transition() — never written directly here.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Set

from app.turn_taking import TurnState, transition, remove_lock, is_terminal_or_idle

logger = logging.getLogger(__name__)

# Default timeout (seconds) when cancelling active tasks during cleanup.
_CLEANUP_TIMEOUT: float = 5.0


# ---------------------------------------------------------------------------
# VoiceSession dataclass
# ---------------------------------------------------------------------------

@dataclass
class VoiceSession:
    """
    Runtime state for a single voice-loop session.

    All mutable turn-state fields are manipulated **only** through
    ``app.turn_taking.transition()``.  Direct assignment to
    ``turn_state`` outside that function is a contract violation.
    """

    session_id: str
    user_id: str = ""

    # ---- turn state (written exclusively by turn_taking.transition) -------
    turn_state: TurnState = TurnState.IDLE
    state_seq: int = 0          # monotonic; incremented on every transition
    turn_seq: int = 0           # monotonic; incremented on IDLE→LISTENING

    # ---- correlation -------------------------------------------------------
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    turn_id: str = ""           # set at start of each new turn

    # ---- cancel events -----------------------------------------------------
    cancel_infer_evt: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_tts_evt: asyncio.Event = field(default_factory=asyncio.Event)

    # ---- timing ------------------------------------------------------------
    created_ts: float = field(default_factory=time.monotonic)
    last_user_audio_ts: float = 0.0
    last_state_change_ts: float = 0.0

    # ---- active tasks -------------------------------------------------------
    # Maps task_name → asyncio.Task so we can cancel them on cleanup.
    active_tasks: Dict[str, asyncio.Task] = field(default_factory=dict)

    # ---- metadata -----------------------------------------------------------
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- helpers -----------------------------------------------------------

    def new_turn_id(self) -> str:
        """Generate and store a fresh turn_id."""
        self.turn_id = f"turn_{self.turn_seq}_{uuid.uuid4().hex[:8]}"
        return self.turn_id

    def reset_cancel_events(self) -> None:
        """Clear both cancel events (prepare for a new turn)."""
        self.cancel_infer_evt.clear()
        self.cancel_tts_evt.clear()

    def signal_cancel_infer(self) -> None:
        """Signal cancellation of the inference stage."""
        self.cancel_infer_evt.set()

    def signal_cancel_tts(self) -> None:
        """Signal cancellation of the TTS stage."""
        self.cancel_tts_evt.set()

    def register_task(self, name: str, task: asyncio.Task) -> None:
        """Register an asyncio task so it can be cleaned up on close."""
        self.active_tasks[name] = task

    def unregister_task(self, name: str) -> None:
        """Remove a task from the registry (call when it finishes)."""
        self.active_tasks.pop(name, None)

    def snapshot(self) -> Dict[str, Any]:
        """Diagnostic snapshot (safe to serialise to JSON)."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turn_state": self.turn_state.value,
            "state_seq": self.state_seq,
            "turn_seq": self.turn_seq,
            "trace_id": self.trace_id,
            "turn_id": self.turn_id,
            "created_ts": self.created_ts,
            "last_user_audio_ts": self.last_user_audio_ts,
            "last_state_change_ts": self.last_state_change_ts,
            "active_task_count": len(self.active_tasks),
            "active_task_names": list(self.active_tasks.keys()),
            "cancel_infer_set": self.cancel_infer_evt.is_set(),
            "cancel_tts_set": self.cancel_tts_evt.is_set(),
        }


# ---------------------------------------------------------------------------
# VoiceSessionManager
# ---------------------------------------------------------------------------

class VoiceSessionManager:
    """
    Create, retrieve, and tear down VoiceSession instances.

    Closing a session:
        1. Cancels all active_tasks with a configurable timeout.
        2. Forces turn_state back to IDLE (via transition if possible,
           direct write only as last resort so the lock is released).
        3. Removes the per-session transition lock.
    """

    def __init__(self, cleanup_timeout: float = _CLEANUP_TIMEOUT):
        self._sessions: Dict[str, VoiceSession] = {}
        self._cleanup_timeout = cleanup_timeout

    # ---- CRUD --------------------------------------------------------------

    def create(
        self,
        user_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> VoiceSession:
        """Create and register a new VoiceSession."""
        sid = session_id or uuid.uuid4().hex
        session = VoiceSession(
            session_id=sid,
            user_id=user_id,
            metadata=metadata or {},
        )
        self._sessions[sid] = session
        logger.info(
            "voice session created  session=%s  user=%s  trace=%s",
            sid, user_id, session.trace_id,
        )
        return session

    def get(self, session_id: str) -> Optional[VoiceSession]:
        """Get session by ID, or None."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> Dict[str, VoiceSession]:
        """Return a shallow copy of all sessions."""
        return dict(self._sessions)

    @property
    def active_count(self) -> int:
        """Number of sessions currently tracked."""
        return len(self._sessions)

    # ---- Cleanup / Close ---------------------------------------------------

    async def close(self, session_id: str, reason: str = "close") -> bool:
        """
        Tear down a voice session cleanly.

        1. Cancel all registered asyncio tasks (with timeout).
        2. Transition state to IDLE (best-effort).
        3. Remove session from the registry and release the lock.

        Returns True if the session existed and was closed.
        """
        session = self._sessions.pop(session_id, None)
        if session is None:
            logger.warning("close called for unknown session=%s", session_id)
            return False

        # --- cancel active tasks -------------------------------------------
        tasks_to_cancel = list(session.active_tasks.values())
        if tasks_to_cancel:
            logger.info(
                "cancelling %d active tasks for session=%s",
                len(tasks_to_cancel), session_id,
            )
            for task in tasks_to_cancel:
                task.cancel()

            # Wait for tasks to finish (with timeout)
            done, pending = await asyncio.wait(
                tasks_to_cancel,
                timeout=self._cleanup_timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
            if pending:
                logger.warning(
                    "%d tasks still pending after %.1fs timeout for session=%s",
                    len(pending), self._cleanup_timeout, session_id,
                )
            session.active_tasks.clear()

        # --- signal cancel events so any blocked coroutines unblock --------
        session.signal_cancel_infer()
        session.signal_cancel_tts()

        # --- force state to IDLE -------------------------------------------
        if not is_terminal_or_idle(session.turn_state):
            ok = await transition(
                session, TurnState.IDLE, reason=f"session_close:{reason}",
                trace_id=session.trace_id,
            )
            if not ok:
                # Last-resort: skip state machine validation (session is
                # being destroyed anyway).  Log loudly.
                logger.error(
                    "forced IDLE on close  session=%s  was=%s",
                    session_id, session.turn_state.value,
                )
                session.turn_state = TurnState.IDLE

        # --- release per-session lock --------------------------------------
        remove_lock(session_id)

        logger.info(
            "voice session closed  session=%s  reason=%s  "
            "turns=%d  state_transitions=%d",
            session_id, reason, session.turn_seq, session.state_seq,
        )
        return True

    async def close_all(self, reason: str = "shutdown") -> int:
        """Close all sessions.  Returns count of sessions closed."""
        sids = list(self._sessions.keys())
        closed = 0
        for sid in sids:
            if await self.close(sid, reason=reason):
                closed += 1
        return closed

    # ---- Reset helper (for recovery paths) --------------------------------

    async def reset_to_idle(
        self, session: VoiceSession, reason: str = "recovery",
    ) -> bool:
        """
        Best-effort reset of a session back to IDLE.

        Used after recoverable failures.  Clears cancel events and
        attempts the state transition.  If the transition is rejected
        (e.g. already IDLE) it returns False but is not an error.
        """
        session.reset_cancel_events()

        if session.turn_state == TurnState.IDLE:
            return True  # already there

        # Try going through RECOVERING first if needed
        if session.turn_state not in (TurnState.RECOVERING, TurnState.INTERRUPTED):
            recover_ok = await transition(
                session, TurnState.RECOVERING, reason=reason,
                trace_id=session.trace_id,
            )
            if not recover_ok:
                # If we can't reach RECOVERING, try IDLE directly
                # (e.g. from LISTENING → IDLE is allowed)
                return await transition(
                    session, TurnState.IDLE, reason=reason,
                    trace_id=session.trace_id,
                )

        # Now in RECOVERING or INTERRUPTED → IDLE
        if session.turn_state == TurnState.INTERRUPTED:
            await transition(
                session, TurnState.RECOVERING, reason=reason,
                trace_id=session.trace_id,
            )

        return await transition(
            session, TurnState.IDLE, reason=reason,
            trace_id=session.trace_id,
        )
