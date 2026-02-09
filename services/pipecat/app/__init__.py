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

__all__ = [
    "TurnState",
    "ALLOWED_TRANSITIONS",
    "transition",
    "get_state_snapshot",
    "is_terminal_or_idle",
    "VoiceSession",
    "VoiceSessionManager",
]
