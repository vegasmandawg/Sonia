"""
v2.8 M4: Operator UX -- OperatorSession tests

Tests:
  - Push-to-talk state machine (valid transitions, invalid transitions)
  - Turn lifecycle (begin_listening -> processing -> responding -> end_turn)
  - Cancel turn from any active state
  - Subsystem health indicators
  - Activity timeline logging
  - Incident snapshot export
  - Input mode management
  - Metrics tracking (turns, cancels, errors, latency)
  - Edge cases (double end_turn, cancel from idle, max activity)
"""

import sys
import time

sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from operator_session import (
    TalkState,
    InputMode,
    SubsystemHealth,
    SubsystemStatus,
    ActivityEntry,
    InvalidStateTransition,
    OperatorSession,
    VALID_TRANSITIONS,
)


# ── State machine basics ───────────────────────────────────────────────

class TestTalkStateMachine:
    """Push-to-talk state transitions."""

    def test_initial_state_is_idle(self):
        op = OperatorSession(session_id="s1")
        assert op.talk_state == TalkState.IDLE

    def test_valid_full_cycle(self):
        """IDLE -> LISTENING -> PROCESSING -> RESPONDING -> IDLE"""
        op = OperatorSession(session_id="s1")
        turn_id = op.begin_listening()
        assert op.talk_state == TalkState.LISTENING
        assert turn_id.startswith("turn_")

        op.begin_processing()
        assert op.talk_state == TalkState.PROCESSING

        op.begin_responding()
        assert op.talk_state == TalkState.RESPONDING

        op.end_turn()
        assert op.talk_state == TalkState.IDLE

    def test_cancel_from_listening(self):
        """LISTENING -> IDLE via cancel."""
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        assert op.talk_state == TalkState.LISTENING
        op.cancel_turn("user_cancel")
        assert op.talk_state == TalkState.IDLE

    def test_cancel_from_processing(self):
        """PROCESSING -> IDLE via cancel."""
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        assert op.talk_state == TalkState.PROCESSING
        op.cancel_turn("timeout")
        assert op.talk_state == TalkState.IDLE

    def test_barge_in_from_responding(self):
        """RESPONDING -> LISTENING (barge-in)."""
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        assert op.talk_state == TalkState.RESPONDING
        # Barge-in: go directly to LISTENING
        turn_id = op.begin_listening()
        assert op.talk_state == TalkState.LISTENING
        assert turn_id.startswith("turn_")

    def test_invalid_idle_to_processing(self):
        """Cannot go from IDLE directly to PROCESSING."""
        op = OperatorSession(session_id="s1")
        with pytest.raises(InvalidStateTransition) as exc_info:
            op.begin_processing()
        assert exc_info.value.from_state == TalkState.IDLE
        assert exc_info.value.to_state == TalkState.PROCESSING

    def test_invalid_idle_to_responding(self):
        """Cannot go from IDLE directly to RESPONDING."""
        op = OperatorSession(session_id="s1")
        with pytest.raises(InvalidStateTransition):
            op.begin_responding()

    def test_invalid_listening_to_responding(self):
        """Cannot skip PROCESSING (LISTENING -> RESPONDING)."""
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        with pytest.raises(InvalidStateTransition):
            op.begin_responding()

    def test_valid_transitions_map_completeness(self):
        """Every TalkState has an entry in VALID_TRANSITIONS."""
        for state in TalkState:
            assert state in VALID_TRANSITIONS, f"Missing transitions for {state}"


# ── Turn lifecycle ─────────────────────────────────────────────────────

class TestTurnLifecycle:
    """Turn ID tracking and metrics."""

    def test_turn_id_created_on_listen(self):
        op = OperatorSession(session_id="s1")
        turn_id = op.begin_listening()
        assert op.current_turn_id == turn_id

    def test_turn_id_cleared_on_end(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        op.end_turn()
        assert op.current_turn_id is None

    def test_turn_id_cleared_on_cancel(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.cancel_turn()
        assert op.current_turn_id is None

    def test_end_turn_from_idle_is_noop(self):
        """Calling end_turn when already idle does nothing."""
        op = OperatorSession(session_id="s1")
        op.end_turn()  # Should not raise
        assert op.talk_state == TalkState.IDLE

    def test_cancel_from_idle_is_noop(self):
        """Calling cancel_turn when already idle does nothing."""
        op = OperatorSession(session_id="s1")
        op.cancel_turn()  # Should not raise
        assert op.talk_state == TalkState.IDLE

    def test_multiple_turns_increment_counter(self):
        op = OperatorSession(session_id="s1")
        for _ in range(3):
            op.begin_listening()
            op.begin_processing()
            op.begin_responding()
            op.end_turn()
        indicators = op.get_indicators()
        assert indicators["metrics"]["total_turns"] == 3

    def test_error_turn_increments_error_counter(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.end_turn(ok=False, error="model_timeout")
        indicators = op.get_indicators()
        assert indicators["metrics"]["total_errors"] == 1
        assert indicators["metrics"]["total_turns"] == 1


# ── Subsystem indicators ──────────────────────────────────────────────

class TestSubsystemIndicators:
    """Subsystem health tracking."""

    def test_default_subsystems_exist(self):
        op = OperatorSession(session_id="s1")
        indicators = op.get_indicators()
        expected = {"model", "memory", "perception", "action", "gateway"}
        assert set(indicators["subsystems"].keys()) == expected

    def test_default_health_is_unknown(self):
        op = OperatorSession(session_id="s1")
        indicators = op.get_indicators()
        for name, ss in indicators["subsystems"].items():
            assert ss["health"] == "unknown", f"{name} should be unknown"

    def test_update_subsystem_health(self):
        op = OperatorSession(session_id="s1")
        op.update_subsystem("model", SubsystemHealth.HEALTHY, latency_ms=42.5, detail="GPT-4o")
        indicators = op.get_indicators()
        model = indicators["subsystems"]["model"]
        assert model["health"] == "healthy"
        assert model["latency_ms"] == 42.5
        assert model["detail"] == "GPT-4o"

    def test_update_subsystem_down_increments_error_count(self):
        op = OperatorSession(session_id="s1")
        op.update_subsystem("memory", SubsystemHealth.DOWN, detail="connection refused")
        op.update_subsystem("memory", SubsystemHealth.DOWN, detail="connection refused again")
        indicators = op.get_indicators()
        assert indicators["subsystems"]["memory"]["error_count"] == 2

    def test_add_new_subsystem(self):
        op = OperatorSession(session_id="s1")
        op.update_subsystem("custom_service", SubsystemHealth.HEALTHY)
        indicators = op.get_indicators()
        assert "custom_service" in indicators["subsystems"]
        assert indicators["subsystems"]["custom_service"]["health"] == "healthy"


# ── Activity timeline ─────────────────────────────────────────────────

class TestActivityTimeline:
    """Activity log and bounded timeline."""

    def test_state_transitions_logged(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        activity = op.get_activity(limit=10)
        assert len(activity) == 2
        assert activity[0]["event_type"] == "state.listening"
        assert activity[1]["event_type"] == "state.processing"

    def test_turn_completed_logged(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        op.end_turn()
        activity = op.get_activity(limit=10)
        # 3 state transitions + 1 turn.completed
        assert len(activity) == 4
        assert activity[-1]["event_type"] == "turn.completed"

    def test_cancel_logged(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.cancel_turn("user_barge")
        activity = op.get_activity(limit=10)
        assert any(e["event_type"] == "turn.cancelled" for e in activity)

    def test_activity_bounded_to_max(self):
        op = OperatorSession(session_id="s1")
        # Generate more than MAX_ACTIVITY entries
        for i in range(op.MAX_ACTIVITY + 50):
            op.begin_listening()
            op.end_turn()
        # Internal list should be bounded
        all_activity = op.get_activity(limit=9999)
        assert len(all_activity) <= op.MAX_ACTIVITY

    def test_activity_limit_parameter(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        op.end_turn()
        # Request only last 2
        activity = op.get_activity(limit=2)
        assert len(activity) == 2

    def test_mode_change_logged(self):
        op = OperatorSession(session_id="s1")
        op.set_input_mode(InputMode.ALWAYS_ON)
        activity = op.get_activity(limit=10)
        assert any(e["event_type"] == "mode.changed" for e in activity)


# ── Incident snapshot ─────────────────────────────────────────────────

class TestIncidentSnapshot:
    """Incident snapshot export for debugging."""

    def test_snapshot_has_required_fields(self):
        op = OperatorSession(session_id="s1")
        snap = op.export_incident_snapshot()
        required = {
            "snapshot_id", "timestamp", "session_id", "talk_state",
            "input_mode", "uptime_seconds", "indicators",
            "recent_activity", "metrics",
        }
        assert required.issubset(snap.keys())

    def test_snapshot_id_is_unique(self):
        op = OperatorSession(session_id="s1")
        s1 = op.export_incident_snapshot()
        s2 = op.export_incident_snapshot()
        assert s1["snapshot_id"] != s2["snapshot_id"]

    def test_snapshot_captures_current_state(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        snap = op.export_incident_snapshot()
        assert snap["talk_state"] == "processing"
        assert snap["session_id"] == "s1"

    def test_snapshot_includes_latency_history(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        op.end_turn()
        snap = op.export_incident_snapshot()
        assert "turn_latencies_last_20" in snap["metrics"]
        assert len(snap["metrics"]["turn_latencies_last_20"]) == 1


# ── Input mode management ─────────────────────────────────────────────

class TestInputMode:
    """Input mode configuration."""

    def test_default_mode_is_push_to_talk(self):
        op = OperatorSession(session_id="s1")
        assert op.input_mode == InputMode.PUSH_TO_TALK

    def test_set_input_mode(self):
        op = OperatorSession(session_id="s1")
        op.set_input_mode(InputMode.TEXT_ONLY)
        assert op.input_mode == InputMode.TEXT_ONLY

    def test_input_mode_in_indicators(self):
        op = OperatorSession(session_id="s1", input_mode=InputMode.ALWAYS_ON)
        indicators = op.get_indicators()
        assert indicators["input_mode"] == "always_on"


# ── Metrics ───────────────────────────────────────────────────────────

class TestMetrics:
    """Metrics tracking."""

    def test_cancel_count_tracked(self):
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.cancel_turn()
        op.begin_listening()
        op.cancel_turn()
        indicators = op.get_indicators()
        assert indicators["metrics"]["total_cancels"] == 2

    def test_avg_latency_computed(self):
        op = OperatorSession(session_id="s1")
        # Do a turn -- latency will be very small but > 0
        op.begin_listening()
        op.begin_processing()
        op.begin_responding()
        op.end_turn()
        indicators = op.get_indicators()
        assert indicators["metrics"]["avg_latency_ms"] >= 0.0

    def test_uptime_increases(self):
        op = OperatorSession(session_id="s1")
        t1 = op.uptime_seconds
        # Minimal sleep to ensure monotonicity
        time.sleep(0.01)
        t2 = op.uptime_seconds
        assert t2 > t1


# ── Dataclass serialization ───────────────────────────────────────────

class TestSerialization:
    """to_dict() methods produce valid JSON-serializable dicts."""

    def test_subsystem_status_to_dict(self):
        ss = SubsystemStatus(
            name="model",
            health=SubsystemHealth.HEALTHY,
            latency_ms=50.0,
            last_check=1234567890.0,
            detail="ok",
            error_count=0,
        )
        d = ss.to_dict()
        assert d["name"] == "model"
        assert d["health"] == "healthy"
        assert d["latency_ms"] == 50.0

    def test_activity_entry_to_dict(self):
        ae = ActivityEntry(
            timestamp=1234567890.0,
            event_type="state.listening",
            detail="Transition idle -> listening",
            turn_id="turn_abc12345",
            duration_ms=0.0,
        )
        d = ae.to_dict()
        assert d["event_type"] == "state.listening"
        assert d["turn_id"] == "turn_abc12345"

    def test_indicators_all_json_serializable(self):
        """get_indicators() must be JSON-serializable (no enums, no objects)."""
        import json
        op = OperatorSession(session_id="s1")
        op.begin_listening()
        op.begin_processing()
        op.update_subsystem("model", SubsystemHealth.HEALTHY, latency_ms=30)
        indicators = op.get_indicators()
        # This will raise if not serializable
        serialized = json.dumps(indicators)
        assert isinstance(serialized, str)
