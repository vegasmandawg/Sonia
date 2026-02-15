"""Voice turn lifecycle state transition tests.

Tests 1-6: Core state transitions (IDLE -> ... -> COMPLETED/ABORTED/ERROR).
Tests 7-8: Invariant enforcement (seq monotonicity, terminal absorption).
"""
import pytest

from services.pipecat.voice.turn_events import TurnEvent
from services.pipecat.voice.turn_state import TurnSnapshot, TurnState, make_initial_snapshot
from services.pipecat.voice.turn_reducer import reduce_turn, Command

# ── Helpers ──────────────────────────────────────────────────────────────

SID = "test-session"
TID = "test-turn"
CID = "corr-001"


def _evt(event_type, seq, **kwargs):
    return TurnEvent(
        event_type=event_type,
        session_id=SID,
        turn_id=TID,
        seq=seq,
        ts_monotonic_ns=seq * 1_000_000,
        correlation_id=CID,
        **kwargs,
    )


def _initial():
    return make_initial_snapshot(SID, TID, CID)


# ── Test 1: IDLE -> LISTENING ────────────────────────────────────────────

class TestTurnLifecycle:

    def test_turn_start_transitions_idle_to_listening(self):
        """Test 1: TURN_STARTED moves IDLE -> LISTENING."""
        s0 = _initial()
        assert s0.state == TurnState.IDLE

        s1, cmds = reduce_turn(s0, _evt("TURN_STARTED", 1))
        assert s1.state == TurnState.LISTENING
        assert s1.seq == 1
        assert len(cmds) == 1
        assert cmds[0].name == "EmitUIState"
        assert cmds[0].args["state"] == "LISTENING"

    def test_asr_final_transitions_listening_to_thinking(self):
        """Test 2: ASR_FINAL moves LISTENING -> THINKING."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        s2, cmds = reduce_turn(s1, _evt("ASR_FINAL", 2))
        assert s2.state == TurnState.THINKING
        assert any(c.name == "StartModelStream" for c in cmds)

    def test_model_first_token_transitions_thinking_to_speaking(self):
        """Test 3: MODEL_FIRST_TOKEN moves THINKING -> SPEAKING."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        s2, _ = reduce_turn(s1, _evt("ASR_FINAL", 2))
        s3, cmds = reduce_turn(s2, _evt("MODEL_FIRST_TOKEN", 3))
        assert s3.state == TurnState.SPEAKING
        assert s3.model_stream_active is True
        assert any(c.name == "StartTTS" for c in cmds)

    def test_tts_end_transitions_speaking_to_completed_once(self):
        """Test 4: TTS_ENDED moves SPEAKING -> COMPLETED (terminal)."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        s2, _ = reduce_turn(s1, _evt("ASR_FINAL", 2))
        s3, _ = reduce_turn(s2, _evt("MODEL_FIRST_TOKEN", 3))
        s4, cmds = reduce_turn(s3, _evt("TTS_ENDED", 4))
        assert s4.state == TurnState.COMPLETED
        assert s4.terminal is True
        assert s4.reason == "normal_completion"
        assert any(c.name == "FinalizeTurn" for c in cmds)

    def test_timeout_transitions_to_aborted(self):
        """Test 5: TURN_TIMEOUT moves any state -> ABORTED."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        s2, cmds = reduce_turn(s1, _evt("TURN_TIMEOUT", 2))
        assert s2.state == TurnState.ABORTED
        assert s2.terminal is True
        assert s2.reason == "TURN_TIMEOUT"
        assert any(c.name == "FinalizeTurn" for c in cmds)

    def test_failure_transitions_to_error(self):
        """Test 6: TURN_FAILED moves any state -> ERROR."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        s2, _ = reduce_turn(s1, _evt("ASR_FINAL", 2))
        s3, cmds = reduce_turn(s2, _evt("TURN_FAILED", 3))
        assert s3.state == TurnState.ERROR
        assert s3.terminal is True
        assert s3.reason == "TURN_FAILED"

    def test_rejects_non_monotonic_seq(self):
        """Test 7: Non-monotonic seq raises ValueError."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        with pytest.raises(ValueError, match="Non-monotonic seq"):
            reduce_turn(s1, _evt("ASR_FINAL", 1))  # same seq
        with pytest.raises(ValueError, match="Non-monotonic seq"):
            reduce_turn(s1, _evt("ASR_FINAL", 0))  # lower seq

    def test_terminal_state_ignores_non_diagnostic_events(self):
        """Test 8: After terminal, events are absorbed with diagnostic."""
        s0 = _initial()
        s1, _ = reduce_turn(s0, _evt("TURN_STARTED", 1))
        s2, _ = reduce_turn(s1, _evt("TURN_TIMEOUT", 2))
        assert s2.state == TurnState.ABORTED

        # Feed another event -- should be absorbed
        s3, cmds = reduce_turn(s2, _evt("ASR_FINAL", 3))
        assert s3.state == TurnState.ABORTED  # no change
        assert s3.seq == 3  # seq advances
        assert any(c.name == "EmitDiagnostic" and c.args["reason"] == "event_after_terminal" for c in cmds)
