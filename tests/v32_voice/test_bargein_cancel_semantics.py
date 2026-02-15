"""Barge-in and cancellation semantics tests.

Tests 9-12: Barge-in routing, cancel token one-shot, idempotency.
"""
import pytest

from services.pipecat.voice.turn_events import TurnEvent
from services.pipecat.voice.turn_state import TurnSnapshot, TurnState, make_initial_snapshot
from services.pipecat.voice.turn_reducer import reduce_turn
from services.pipecat.voice.cancel_registry import CancelRegistry

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


def _to_speaking():
    """Helper: drive snapshot from IDLE to SPEAKING."""
    s = make_initial_snapshot(SID, TID, CID)
    s, _ = reduce_turn(s, _evt("TURN_STARTED", 1))
    s, _ = reduce_turn(s, _evt("ASR_FINAL", 2))
    s, _ = reduce_turn(s, _evt("MODEL_FIRST_TOKEN", 3))
    assert s.state == TurnState.SPEAKING
    return s


def _to_thinking():
    """Helper: drive snapshot from IDLE to THINKING."""
    s = make_initial_snapshot(SID, TID, CID)
    s, _ = reduce_turn(s, _evt("TURN_STARTED", 1))
    s, _ = reduce_turn(s, _evt("ASR_FINAL", 2))
    assert s.state == TurnState.THINKING
    return s


# ── Tests ────────────────────────────────────────────────────────────────

class TestBargeInCancelSemantics:

    def test_barge_in_from_speaking_routes_to_interrupting(self):
        """Test 9: BARGE_IN from SPEAKING -> INTERRUPTING with StopTTS + CancelModelStream."""
        s = _to_speaking()
        s2, cmds = reduce_turn(s, _evt("BARGE_IN_REQUESTED", 4))
        assert s2.state == TurnState.INTERRUPTING
        assert s2.cancel_requested is True
        cmd_names = [c.name for c in cmds]
        assert "StopTTS" in cmd_names
        assert "CancelModelStream" in cmd_names
        assert "EmitUIState" in cmd_names

    def test_cancel_request_routes_interrupting_to_cancelling(self):
        """Test 10: CANCEL_ACK in INTERRUPTING -> CANCELLING."""
        s = _to_speaking()
        s2, _ = reduce_turn(s, _evt("BARGE_IN_REQUESTED", 4))
        assert s2.state == TurnState.INTERRUPTING

        s3, cmds = reduce_turn(s2, _evt("CANCEL_ACK", 5))
        assert s3.state == TurnState.CANCELLING
        assert any(c.name == "EmitUIState" and c.args["state"] == "CANCELLING" for c in cmds)

    def test_cancel_token_one_shot_consumption(self):
        """Test 11: CancelRegistry enforces one-shot request and consume."""
        reg = CancelRegistry()

        # First request succeeds
        assert reg.request(SID, TID) is True
        # Duplicate request fails
        assert reg.request(SID, TID) is False

        # First consume succeeds
        assert reg.consume(SID, TID) is True
        # Duplicate consume fails
        assert reg.consume(SID, TID) is False

        # Consume without request fails
        assert reg.consume(SID, "other-turn") is False

    def test_barge_in_idempotent_under_duplicate_events(self):
        """Test 12: Second BARGE_IN in INTERRUPTING doesn't cause double transition.

        Specifically verifies no direct SPEAKING -> LISTENING bypass exists.
        """
        s = _to_speaking()
        s2, cmds1 = reduce_turn(s, _evt("BARGE_IN_REQUESTED", 4))
        assert s2.state == TurnState.INTERRUPTING

        # Second barge-in in INTERRUPTING: should be a no-op (diagnostic)
        s3, cmds2 = reduce_turn(s2, _evt("BARGE_IN_REQUESTED", 5))
        # Should not jump to LISTENING -- must go through CANCELLING
        assert s3.state != TurnState.LISTENING
        # It's either still INTERRUPTING or a diagnostic no-op
        assert s3.state == TurnState.INTERRUPTING
        assert any(c.name == "EmitDiagnostic" for c in cmds2)

    def test_cancelling_reentry_to_listening(self):
        """Cancelling + TURN_STARTED -> LISTENING (re-entry after cancel)."""
        s = _to_speaking()
        s2, _ = reduce_turn(s, _evt("BARGE_IN_REQUESTED", 4))
        s3, _ = reduce_turn(s2, _evt("CANCEL_ACK", 5))
        assert s3.state == TurnState.CANCELLING

        s4, cmds = reduce_turn(s3, _evt("TURN_STARTED", 6))
        assert s4.state == TurnState.LISTENING
        assert s4.cancel_requested is False
        assert s4.tts_active is False
        assert s4.model_stream_active is False

    def test_barge_in_from_thinking(self):
        """BARGE_IN from THINKING -> INTERRUPTING (no TTS to stop)."""
        s = _to_thinking()
        s2, cmds = reduce_turn(s, _evt("BARGE_IN_REQUESTED", 3))
        assert s2.state == TurnState.INTERRUPTING
        cmd_names = [c.name for c in cmds]
        assert "CancelModelStream" in cmd_names
        # No StopTTS since TTS hasn't started
        assert "StopTTS" not in cmd_names

    def test_no_speaking_to_listening_bypass(self):
        """Verify there is no direct transition from SPEAKING to LISTENING.

        Must always go through INTERRUPTING -> CANCELLING -> LISTENING.
        """
        s = _to_speaking()

        # Try all non-barge-in events that might cause a transition
        for et in ["ASR_FINAL", "ASR_PARTIAL", "TURN_STARTED"]:
            s2, cmds = reduce_turn(s, _evt(et, 100))
            assert s2.state != TurnState.LISTENING, (
                f"Direct SPEAKING -> LISTENING bypass via {et}!"
            )
