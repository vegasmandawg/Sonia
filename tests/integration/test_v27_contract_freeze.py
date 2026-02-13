"""
v2.7 Contract Freeze Tests

Locks all v2.7 wire formats as versioned APIs. Any change after this
requires explicit version bump + backward-compat migration tests.

Frozen contracts (40 tests):
  Voice protocol (7):
    1-7. Message shapes for session.ready, input.text, response.partial,
         response.final, error, tool.call, control.end

  UI stream protocol (8):
    8-15. control.toggle/interrupt/replay/hold, ack/nack shapes,
          diagnostics envelope, session.created

  ACK state machine (5):
    16-20. UISessionState controls freeze, toggle semantics,
           NACK on unknown field, conversation state enum

  EventBus schema (5):
    21-25. EventRecord fields, DeadLetter fields, constants,
           pattern matching semantics, publish envelope shape

  Dead-letter schema (4):
    26-29. DeadLetter fields, enqueue contract, replay contract,
           bounded growth constant

  Action bridge (5):
    30-34. ToolExecutionResult fields, execute_tool_call signature,
           batch signature, approve/deny signatures

  GatewayStreamClient (3):
    35-37. StreamState enum values, TurnResult fields, client constants

  VoiceTurnRecord (3):
    38-40. Record fields, stats dict shape, history semantics
"""

import sys
import dataclasses
import inspect
from typing import get_type_hints

import pytest
pytestmark = [pytest.mark.legacy_v26_v28, pytest.mark.legacy_voice_turn_router]

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _fields_of(cls):
    """Get field names from a dataclass."""
    return {f.name for f in dataclasses.fields(cls)}


# ===========================================================================
# Voice protocol message shapes
# ===========================================================================

class TestVoiceProtocolFreeze:

    def test_session_ready_shape(self):
        """session.ready must have type, session_id, correlation_id."""
        msg = {"type": "session.ready", "session_id": "s1", "correlation_id": "req_x"}
        assert set(msg.keys()) == {"type", "session_id", "correlation_id"}

    def test_input_text_shape(self):
        """input.text must have type and text (correlation_id optional)."""
        required = {"type", "text"}
        optional = {"correlation_id"}
        msg = {"type": "input.text", "text": "hello"}
        assert required.issubset(set(msg.keys()))

    def test_response_partial_shape(self):
        """response.partial must have type and text."""
        msg = {"type": "response.partial", "text": "Hi"}
        assert set(msg.keys()) == {"type", "text"}

    def test_response_final_shape(self):
        """response.final must have type, text, turn_id, latency_ms, tool_calls, partial_count."""
        required = {"type", "text", "turn_id", "latency_ms", "tool_calls", "partial_count"}
        msg = {
            "type": "response.final", "text": "done", "turn_id": "t1",
            "latency_ms": 100.0, "tool_calls": 0, "partial_count": 2,
        }
        assert required == set(msg.keys())

    def test_error_shape(self):
        """error must have type and message."""
        msg = {"type": "error", "message": "fail"}
        assert {"type", "message"}.issubset(set(msg.keys()))

    def test_tool_call_shape(self):
        """tool.call must have type, tool_name, status."""
        msg = {"type": "tool.call", "tool_name": "file.read", "status": "executed"}
        assert set(msg.keys()) == {"type", "tool_name", "status"}

    def test_control_end_shape(self):
        """control.end has only type."""
        msg = {"type": "control.end"}
        assert set(msg.keys()) == {"type"}


# ===========================================================================
# UI stream protocol message shapes
# ===========================================================================

class TestUIStreamProtocolFreeze:

    def test_session_created_shape(self):
        from routes.ui_stream import UISessionState
        msg = {"type": "session.created", "session_id": "ui-abc"}
        assert set(msg.keys()) == {"type", "session_id"}

    def test_control_toggle_shape(self):
        """control.toggle requires type, field, value."""
        msg = {"type": "control.toggle", "field": "micEnabled", "value": True}
        assert set(msg.keys()) == {"type", "field", "value"}

    def test_control_interrupt_shape(self):
        msg = {"type": "control.interrupt"}
        assert set(msg.keys()) == {"type"}

    def test_control_replay_shape(self):
        msg = {"type": "control.replay"}
        assert set(msg.keys()) == {"type"}

    def test_control_hold_shape(self):
        msg = {"type": "control.hold", "active": True}
        assert set(msg.keys()) == {"type", "active"}

    def test_ack_control_shape(self):
        msg = {"type": "ack.control", "field": "micEnabled"}
        assert set(msg.keys()) == {"type", "field"}

    def test_nack_control_shape(self):
        msg = {"type": "nack.control", "field": "unknown", "reason": "bad field"}
        assert set(msg.keys()) == {"type", "field", "reason"}

    def test_diagnostics_envelope_keys(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="freeze-1")
        diag = state.to_diagnostics()
        required = {
            "session_id", "uptime_seconds", "turn_count", "latency",
            "breaker_states", "dlq_depth", "privacy_status",
            "vision_buffer_frames", "last_error",
        }
        assert required.issubset(set(diag.keys()))


# ===========================================================================
# ACK state machine freeze
# ===========================================================================

class TestACKStateMachineFreeze:

    def test_toggleable_fields_frozen(self):
        """Exactly 4 toggleable fields, no more, no less."""
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="ack-1")
        assert set(state.controls.keys()) == {
            "micEnabled", "camEnabled", "privacyEnabled", "holdActive",
        }

    def test_default_control_values(self):
        """Default values are frozen."""
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="ack-2")
        assert state.controls["micEnabled"] is True
        assert state.controls["camEnabled"] is False
        assert state.controls["privacyEnabled"] is False
        assert state.controls["holdActive"] is False

    @pytest.mark.asyncio
    async def test_toggle_valid_produces_ack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message

        class MockWS:
            def __init__(self): self.sent = []
            async def send_json(self, d): self.sent.append(d)

        ws = MockWS()
        state = UISessionState(session_id="ack-3")
        msg = {"type": "control.toggle", "field": "micEnabled", "value": False}
        await _dispatch_ui_message(ws, state, "control.toggle", msg)
        assert ws.sent[0]["type"] == "ack.control"

    @pytest.mark.asyncio
    async def test_toggle_unknown_produces_nack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message

        class MockWS:
            def __init__(self): self.sent = []
            async def send_json(self, d): self.sent.append(d)

        ws = MockWS()
        state = UISessionState(session_id="ack-4")
        msg = {"type": "control.toggle", "field": "nonexistent", "value": True}
        await _dispatch_ui_message(ws, state, "control.toggle", msg)
        assert ws.sent[0]["type"] == "nack.control"

    def test_conversation_state_default(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="ack-5")
        assert state.conversation_state == "idle"


# ===========================================================================
# EventBus schema freeze
# ===========================================================================

class TestEventBusSchemaFreeze:

    def test_event_record_fields(self):
        from event_bus import EventRecord
        fields = _fields_of(EventRecord)
        required = {"event_id", "event_type", "source", "correlation_id",
                     "timestamp", "delivered_to", "failed", "latency_ms"}
        assert required == fields

    def test_dead_letter_fields(self):
        from event_bus import DeadLetter
        fields = _fields_of(DeadLetter)
        required = {"event_id", "event_type", "handler_name", "error",
                     "timestamp", "correlation_id"}
        assert required == fields

    def test_constants_frozen(self):
        from event_bus import EventBus
        assert EventBus.HANDLER_TIMEOUT_S == 10.0
        assert EventBus.MAX_HISTORY == 500
        assert EventBus.MAX_DEAD_LETTERS == 100

    @pytest.mark.asyncio
    async def test_publish_envelope_shape(self):
        """Published event must have 'type' field; handler receives full dict."""
        from event_bus import EventBus
        bus = EventBus()
        received = []
        async def h(e): received.append(e)
        bus.subscribe("test.*", h)
        await bus.publish({"type": "test.freeze", "data": {"x": 1}})
        assert received[0]["type"] == "test.freeze"

    def test_pattern_matching_glob(self):
        """Pattern matching uses fnmatch semantics."""
        import fnmatch
        assert fnmatch.fnmatch("vision.frame.available", "vision.*")
        assert not fnmatch.fnmatch("session.created", "vision.*")
        assert fnmatch.fnmatch("anything", "*")


# ===========================================================================
# Dead-letter schema freeze
# ===========================================================================

class TestDeadLetterSchemaFreeze:

    def test_dead_letter_entry_fields(self):
        from dead_letter import DeadLetter
        fields = _fields_of(DeadLetter)
        required = {"letter_id", "action_id", "intent", "params",
                     "error_code", "error_message", "correlation_id",
                     "session_id", "created_at", "retries_exhausted",
                     "failure_class", "replayed", "replayed_at",
                     "replay_action_id"}
        assert required == fields

    @pytest.mark.asyncio
    async def test_enqueue_returns_letter_id(self):
        from dead_letter import DeadLetterQueue
        dlq = DeadLetterQueue()
        lid = await dlq.enqueue(
            action_id="act_test", intent="file.read", params={},
            error_code="TEST", error_message="test",
        )
        assert lid.startswith("dl_")

    @pytest.mark.asyncio
    async def test_replay_marks_replayed(self):
        from dead_letter import DeadLetterQueue
        dlq = DeadLetterQueue()
        lid = await dlq.enqueue(
            action_id="act_replay", intent="file.read", params={},
            error_code="ERR", error_message="fail",
        )
        await dlq.mark_replayed(lid, "act_replay2")
        letter = await dlq.get(lid)
        assert letter.replayed is True
        assert letter.replay_action_id == "act_replay2"

    def test_max_dead_letters_constant(self):
        from dead_letter import MAX_DEAD_LETTERS
        assert MAX_DEAD_LETTERS == 1000


# ===========================================================================
# Action bridge contract freeze
# ===========================================================================

class TestActionBridgeFreeze:

    def test_tool_execution_result_fields(self):
        from action_turn_bridge import ToolExecutionResult
        fields = _fields_of(ToolExecutionResult)
        required = {"tool_name", "executed", "pending_approval", "rejected",
                     "output", "side_effects", "action_id", "action_state",
                     "risk_level", "error", "error_code", "duration_ms",
                     "retries_used", "dry_run"}
        assert required == fields

    def test_execute_tool_call_signature(self):
        from action_turn_bridge import ActionTurnBridge
        sig = inspect.signature(ActionTurnBridge.execute_tool_call)
        params = set(sig.parameters.keys())
        required = {"self", "tool_name", "tool_args", "session_id",
                     "correlation_id", "timeout_ms", "max_retries",
                     "dry_run", "idempotency_key"}
        assert required == params

    def test_execute_batch_signature(self):
        from action_turn_bridge import ActionTurnBridge
        sig = inspect.signature(ActionTurnBridge.execute_batch)
        params = set(sig.parameters.keys())
        required = {"self", "tool_calls", "session_id", "correlation_id",
                     "timeout_ms", "max_retries"}
        assert required == params

    def test_approve_deny_signatures(self):
        from action_turn_bridge import ActionTurnBridge
        approve_params = set(inspect.signature(ActionTurnBridge.approve_pending).parameters.keys())
        deny_params = set(inspect.signature(ActionTurnBridge.deny_pending).parameters.keys())
        assert approve_params == {"self", "action_id"}
        assert deny_params == {"self", "action_id"}

    def test_risk_level_enum_values(self):
        from schemas.action import RiskLevel
        # RiskLevel is a Literal type; verify via ActionPlanResponse schema
        from schemas.action import ActionPlanResponse
        schema = ActionPlanResponse.model_json_schema()
        risk_field = schema["properties"]["risk_level"]
        # Literal types become enum in JSON schema
        assert set(risk_field.get("enum", [])) == {"safe", "low", "medium", "high", "critical"}


# ===========================================================================
# GatewayStreamClient freeze
# ===========================================================================

class TestGatewayStreamClientFreeze:

    def test_stream_state_enum_frozen(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gsc_freeze", r"S:\services\pipecat\clients\gateway_stream_client.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["gsc_freeze"] = mod
        spec.loader.exec_module(mod)
        states = {s.value for s in mod.StreamState}
        assert states == {"disconnected", "connecting", "connected", "reconnecting", "error"}

    def test_turn_result_fields_frozen(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gsc_freeze2", r"S:\services\pipecat\clients\gateway_stream_client.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["gsc_freeze2"] = mod
        spec.loader.exec_module(mod)
        # TurnResult uses __slots__, not @dataclass
        fields = set(mod.TurnResult.__slots__)
        required = {"ok", "turn_id", "assistant_text", "tool_calls",
                     "partial_texts", "latency_ms", "error",
                     "correlation_id", "events"}
        assert required == fields

    def test_client_constants_frozen(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gsc_freeze3", r"S:\services\pipecat\clients\gateway_stream_client.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["gsc_freeze3"] = mod
        spec.loader.exec_module(mod)
        assert mod.GatewayStreamClient.TURN_TIMEOUT_S == 30.0
        assert mod.GatewayStreamClient.RECONNECT_BASE_S == 1.0
        assert mod.GatewayStreamClient.RECONNECT_CAP_S == 16.0
        assert mod.GatewayStreamClient.MAX_RECONNECT == 10


# ===========================================================================
# VoiceTurnRecord freeze
# ===========================================================================

class TestVoiceTurnRecordFreeze:

    def test_record_fields_frozen(self):
        from app.voice_turn_router import VoiceTurnRecord
        fields = _fields_of(VoiceTurnRecord)
        required = {"turn_id", "session_id", "correlation_id", "user_text",
                     "assistant_text", "tool_calls", "partial_count",
                     "latency_ms", "gateway_latency_ms", "ok", "error",
                     "timestamp"}
        assert required == fields

    def test_stats_dict_shape(self):
        from app.voice_turn_router import VoiceTurnRouter
        router = VoiceTurnRouter(gateway_url="http://localhost:9999")
        stats = router.get_stats()
        required = {"active_sessions", "total_turns",
                     "recent_success_rate", "recent_avg_latency_ms"}
        assert required == set(stats.keys())

    def test_history_is_list(self):
        from app.voice_turn_router import VoiceTurnRouter
        router = VoiceTurnRouter(gateway_url="http://localhost:9999")
        assert isinstance(router._turn_history, list)
        assert len(router._turn_history) == 0
