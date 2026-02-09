"""
Pipecat App — Voice Loop Hardening Modules

This package provides deterministic turn state management,
interrupt handling, watchdogs, and telemetry for the voice pipeline.
"""

from app.turn_taking import (
    TurnState,
    ALLOWED_TRANSITIONS,
    transition,
    get_state_snapshot,
    is_terminal_or_idle,
)
from app.session_manager import VoiceSession, VoiceSessionManager
from app.interruptions import handle_interrupt, InterruptResult, clear_interrupt_state
from app.tts_client import synthesize_cancellable
from app.model_router_client import infer_cancellable, close_client as close_model_client
from app.watchdog import run_with_timeout, StageTimeout, WatchdogResult
from app.asr_client import transcribe_guarded

__all__ = [
    "TurnState",
    "ALLOWED_TRANSITIONS",
    "transition",
    "get_state_snapshot",
    "is_terminal_or_idle",
    "VoiceSession",
    "VoiceSessionManager",
    "handle_interrupt",
    "InterruptResult",
    "clear_interrupt_state",
    "synthesize_cancellable",
    "infer_cancellable",
    "close_model_client",
    "run_with_timeout",
    "StageTimeout",
    "WatchdogResult",
    "transcribe_guarded",
]
