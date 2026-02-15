"""Pure reducer for voice turn lifecycle.

Contract:
    next_state, commands = reduce_turn(current_state, event)

Rules:
    1. Reducer is pure -- no side effects.
    2. Commands are side-effect intents only.
    3. seq must be strictly monotonic.
    4. Terminal states are absorbing (ignore non-diagnostic events).
    5. Barge-in always routes through INTERRUPTING -> CANCELLING -> LISTENING.
    6. A turn produces at most one terminal state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .turn_events import TurnEvent
from .turn_state import TurnSnapshot, TurnState, TERMINAL_STATES


@dataclass(frozen=True)
class Command:
    """Side-effect intent emitted by the reducer.

    Execution is handled externally. Commands are idempotent via
    idempotency_key = f"{session_id}:{turn_id}:{seq}:{name}"
    """
    name: str
    args: dict

    @property
    def idempotency_key_suffix(self) -> str:
        """Returns the command-type portion of the idempotency key."""
        return self.name


# ── Transition Table ─────────────────────────────────────────────────────
#
# State           x Event               -> Next State        + Commands
# -----------------------------------------------------------------------
# IDLE              TURN_STARTED         -> LISTENING         + EmitUIState
# LISTENING         ASR_PARTIAL          -> LISTENING         + (no-op, update)
# LISTENING         ASR_FINAL            -> THINKING          + StartModelStream
# THINKING          MODEL_FIRST_TOKEN    -> SPEAKING          + StartTTS
# THINKING          MODEL_STREAM_ENDED   -> THINKING          + (no-op, wait TTS)
# SPEAKING          TTS_STARTED          -> SPEAKING          + (no-op, update)
# SPEAKING          TTS_CHUNK            -> SPEAKING          + (no-op, update)
# SPEAKING          TTS_ENDED            -> COMPLETED         + FinalizeTurn
# SPEAKING          MODEL_STREAM_ENDED   -> SPEAKING          + (update flag)
# THINKING|SPEAKING BARGE_IN_REQUESTED   -> INTERRUPTING      + StopTTS, CancelModelStream
# INTERRUPTING      CANCEL_REQUESTED     -> CANCELLING        + EmitUIState
# INTERRUPTING      CANCEL_ACK           -> CANCELLING        + EmitUIState
# CANCELLING        TURN_STARTED         -> LISTENING         + EmitUIState (re-entry)
# CANCELLING        CANCEL_ACK           -> CANCELLING        + (absorb ack)
# ANY               TURN_TIMEOUT         -> ABORTED           + FinalizeTurn
# ANY               TURN_FAILED          -> ERROR             + FinalizeTurn
# TERMINAL          ANY                  -> TERMINAL (absorb) + EmitDiagnostic
# -----------------------------------------------------------------------


def reduce_turn(snapshot: TurnSnapshot, event: TurnEvent) -> Tuple[TurnSnapshot, List[Command]]:
    """Pure reducer: (snapshot, event) -> (next_snapshot, commands).

    Raises ValueError on non-monotonic seq or session/turn mismatch.
    """
    # ── Invariant checks ─────────────────────────────────────────────
    if event.seq <= snapshot.seq:
        raise ValueError(
            f"Non-monotonic seq: event={event.seq} snapshot={snapshot.seq}"
        )
    if snapshot.session_id != event.session_id or snapshot.turn_id != event.turn_id:
        raise ValueError(
            f"Session/turn mismatch: snapshot=({snapshot.session_id},{snapshot.turn_id}) "
            f"event=({event.session_id},{event.turn_id})"
        )

    s = snapshot
    cmds: List[Command] = []
    et = event.event_type

    # ── Terminal absorber ────────────────────────────────────────────
    if s.state in TERMINAL_STATES:
        return (
            s.evolve(seq=event.seq),
            [Command("EmitDiagnostic", {"reason": "event_after_terminal", "event_type": et})]
        )

    # ── Fatal events (any non-terminal state) ────────────────────────
    if et == "TURN_TIMEOUT":
        return (
            s.evolve(state=TurnState.ABORTED, seq=event.seq, terminal=True, reason="TURN_TIMEOUT"),
            [Command("FinalizeTurn", {"turn_id": s.turn_id, "reason": "TURN_TIMEOUT"})]
        )

    if et == "TURN_FAILED":
        return (
            s.evolve(state=TurnState.ERROR, seq=event.seq, terminal=True, reason="TURN_FAILED"),
            [Command("FinalizeTurn", {"turn_id": s.turn_id, "reason": "TURN_FAILED"})]
        )

    # ── IDLE ─────────────────────────────────────────────────────────
    if s.state == TurnState.IDLE:
        if et == "TURN_STARTED":
            return (
                s.evolve(state=TurnState.LISTENING, seq=event.seq),
                [Command("EmitUIState", {"state": "LISTENING"})]
            )

    # ── LISTENING ────────────────────────────────────────────────────
    elif s.state == TurnState.LISTENING:
        if et == "ASR_PARTIAL":
            return s.evolve(seq=event.seq), []

        if et == "ASR_FINAL":
            return (
                s.evolve(state=TurnState.THINKING, seq=event.seq),
                [Command("StartModelStream", {"turn_id": s.turn_id})]
            )

    # ── THINKING ─────────────────────────────────────────────────────
    elif s.state == TurnState.THINKING:
        if et == "MODEL_FIRST_TOKEN":
            return (
                s.evolve(state=TurnState.SPEAKING, seq=event.seq, model_stream_active=True),
                [Command("StartTTS", {"turn_id": s.turn_id})]
            )

        if et == "MODEL_STREAM_ENDED":
            return s.evolve(seq=event.seq, model_stream_active=False), []

        if et == "BARGE_IN_REQUESTED":
            return (
                s.evolve(state=TurnState.INTERRUPTING, seq=event.seq, cancel_requested=True),
                [
                    Command("CancelModelStream", {"turn_id": s.turn_id}),
                    Command("EmitUIState", {"state": "INTERRUPTING"}),
                ]
            )

    # ── SPEAKING ─────────────────────────────────────────────────────
    elif s.state == TurnState.SPEAKING:
        if et == "TTS_STARTED":
            return s.evolve(seq=event.seq, tts_active=True), []

        if et == "TTS_CHUNK":
            return s.evolve(seq=event.seq), []

        if et == "TTS_ENDED":
            return (
                s.evolve(
                    state=TurnState.COMPLETED, seq=event.seq, terminal=True,
                    tts_active=False, reason="normal_completion",
                ),
                [Command("FinalizeTurn", {"turn_id": s.turn_id, "reason": "normal_completion"})]
            )

        if et == "MODEL_STREAM_ENDED":
            return s.evolve(seq=event.seq, model_stream_active=False), []

        if et == "BARGE_IN_REQUESTED":
            return (
                s.evolve(state=TurnState.INTERRUPTING, seq=event.seq, cancel_requested=True),
                [
                    Command("StopTTS", {"turn_id": s.turn_id}),
                    Command("CancelModelStream", {"turn_id": s.turn_id}),
                    Command("EmitUIState", {"state": "INTERRUPTING"}),
                ]
            )

    # ── INTERRUPTING ─────────────────────────────────────────────────
    elif s.state == TurnState.INTERRUPTING:
        if et in ("CANCEL_REQUESTED", "CANCEL_ACK"):
            return (
                s.evolve(state=TurnState.CANCELLING, seq=event.seq),
                [Command("EmitUIState", {"state": "CANCELLING"})]
            )

        # Absorb stale TTS/model events during interruption
        if et in ("TTS_CHUNK", "TTS_ENDED", "MODEL_STREAM_ENDED"):
            return s.evolve(seq=event.seq, tts_active=False, model_stream_active=False), []

    # ── CANCELLING ───────────────────────────────────────────────────
    elif s.state == TurnState.CANCELLING:
        if et == "TURN_STARTED":
            # Re-entry: new turn after cancellation
            return (
                s.evolve(
                    state=TurnState.LISTENING, seq=event.seq,
                    tts_active=False, model_stream_active=False,
                    cancel_requested=False,
                ),
                [Command("EmitUIState", {"state": "LISTENING"})]
            )

        if et == "CANCEL_ACK":
            # Absorb additional acks
            return s.evolve(seq=event.seq), []

        # Absorb stale events during cancellation
        if et in ("TTS_CHUNK", "TTS_ENDED", "MODEL_STREAM_ENDED"):
            return s.evolve(seq=event.seq, tts_active=False, model_stream_active=False), []

    # ── Default: deterministic no-op ─────────────────────────────────
    return (
        s.evolve(seq=event.seq),
        [Command("EmitDiagnostic", {
            "reason": "no_transition",
            "event_type": et,
            "state": s.state.value,
        })]
    )
