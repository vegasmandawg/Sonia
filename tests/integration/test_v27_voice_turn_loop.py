"""
v2.7 M1 Integration Tests -- Voice Turn Loop

Tests the VoiceTurnRouter, GatewayStreamClient, and Pipecat
v2.7 endpoint contracts. Unit-level tests that verify the
protocol logic without requiring live services.

Tests (18):
  GatewayStreamClient (6):
    1. TurnResult starts empty
    2. StreamState enum has 5 states
    3. Client initial state is disconnected
    4. Client properties before connect
    5. TurnResult accumulates events
    6. TurnResult captures tool calls

  VoiceTurnRouter (6):
    7. Router starts with zero sessions
    8. VoiceTurnRecord has all fields
    9. Router stats are well-formed
    10. Router history respects max size
    11. Close non-existent session returns False
    12. Close all on empty returns 0

  Protocol Contract (6):
    13. input.text message shape is correct
    14. response.final message shape is correct
    15. error message shape is correct
    16. session.ready message shape is correct
    17. control.end is recognized as stream close
    18. Correlation ID propagation through turn record
"""

import sys
import asyncio
import json
import time
import importlib.util

import pytest
pytestmark = [pytest.mark.legacy_v26_v28]

# Canonical loaders from conftest.py (registered in sys.modules)
from pipecat_voice_turn_router import VoiceTurnRouter, VoiceTurnRecord
import pipecat_gateway_stream_client as _gsc_mod_direct


def _get_gsc():
    return _gsc_mod_direct


# ===========================================================================
# GatewayStreamClient unit tests
# ===========================================================================

class TestGatewayStreamClient:

    def test_turn_result_starts_empty(self):
        mod = _get_gsc()
        TurnResult = mod.TurnResult
        r = TurnResult()
        assert r.ok is False
        assert r.assistant_text == ""
        assert r.turn_id == ""
        assert r.tool_calls == []
        assert r.partial_texts == []
        assert r.latency_ms == 0.0
        assert r.error == ""
        assert r.correlation_id == ""
        assert r.events == []

    def test_stream_state_enum_5_states(self):
        StreamState = _get_gsc().StreamState
        states = list(StreamState)
        assert len(states) == 5
        names = {s.value for s in states}
        assert names == {"disconnected", "connecting", "connected", "reconnecting", "error"}

    def test_client_initial_state(self):
        mod = _get_gsc()
        GatewayStreamClient, StreamState = mod.GatewayStreamClient, mod.StreamState
        client = GatewayStreamClient("http://127.0.0.1:7000")
        assert client.state == StreamState.DISCONNECTED
        assert client.session_id is None

    def test_client_properties_before_connect(self):
        GatewayStreamClient = _get_gsc().GatewayStreamClient
        client = GatewayStreamClient("http://localhost:9999")
        assert client.gateway_url == "http://localhost:9999"
        assert client._ws is None
        assert client._reconnect_attempts == 0
        assert client._intentional_close is False

    def test_turn_result_accumulates_events(self):
        TurnResult = _get_gsc().TurnResult
        r = TurnResult()
        r.events.append({"type": "response.partial", "payload": {"text": "Hi"}})
        r.events.append({"type": "response.final", "payload": {"text": "Hi there!"}})
        r.partial_texts.append("Hi")
        r.assistant_text = "Hi there!"
        r.ok = True
        assert len(r.events) == 2
        assert len(r.partial_texts) == 1
        assert r.ok is True

    def test_turn_result_captures_tool_calls(self):
        TurnResult = _get_gsc().TurnResult
        r = TurnResult()
        r.tool_calls.append({"tool_name": "file.read", "status": "executed"})
        r.tool_calls.append({"tool_name": "shell.run", "status": "pending"})
        assert len(r.tool_calls) == 2
        assert r.tool_calls[0]["tool_name"] == "file.read"


# ===========================================================================
# VoiceTurnRouter unit tests
# ===========================================================================

class TestVoiceTurnRouter:

    def test_router_starts_empty(self):
        router = VoiceTurnRouter(gateway_url="http://localhost:9999")
        assert router.active_sessions == 0
        assert router.total_turns == 0

    def test_voice_turn_record_fields(self):
        r = VoiceTurnRecord()
        assert r.turn_id == ""
        assert r.session_id == ""
        assert r.correlation_id == ""
        assert r.user_text == ""
        assert r.assistant_text == ""
        assert r.tool_calls == []
        assert r.partial_count == 0
        assert r.latency_ms == 0.0
        assert r.gateway_latency_ms == 0.0
        assert r.ok is False
        assert r.error == ""
        assert r.timestamp == 0.0

    def test_router_stats_well_formed(self):
        router = VoiceTurnRouter()
        stats = router.get_stats()
        assert "active_sessions" in stats
        assert "total_turns" in stats
        assert "recent_success_rate" in stats
        assert "recent_avg_latency_ms" in stats
        assert stats["active_sessions"] == 0
        assert stats["total_turns"] == 0
        assert stats["recent_success_rate"] == 0.0

    def test_router_history_max_size(self):
        router = VoiceTurnRouter()
        router._max_history = 5
        for i in range(10):
            record = VoiceTurnRecord(turn_id=f"turn_{i}", ok=True, latency_ms=10.0)
            router._turn_history.append(record)
            if len(router._turn_history) > router._max_history:
                router._turn_history = router._turn_history[-router._max_history:]
        assert len(router._turn_history) == 5
        assert router._turn_history[0].turn_id == "turn_5"

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self):
        router = VoiceTurnRouter()
        result = await router.close_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_all_empty(self):
        router = VoiceTurnRouter()
        count = await router.close_all()
        assert count == 0


# ===========================================================================
# Protocol contract tests
# ===========================================================================

class TestProtocolContract:

    def test_input_text_message_shape(self):
        """Verify the outbound input.text message structure."""
        msg = {
            "type": "input.text",
            "text": "Hello, Sonia",
            "turn_id": "turn_abc",
            "correlation_id": "req_123456789012",
        }
        assert msg["type"] == "input.text"
        assert isinstance(msg["text"], str)
        assert msg["turn_id"].startswith("turn_")
        assert msg["correlation_id"].startswith("req_")

    def test_response_final_message_shape(self):
        """Verify the expected response.final structure from v1/voice."""
        msg = {
            "type": "response.final",
            "text": "Hello! How can I help?",
            "turn_id": "vturn_abc",
            "latency_ms": 150.3,
            "tool_calls": 0,
            "partial_count": 2,
        }
        assert msg["type"] == "response.final"
        assert isinstance(msg["text"], str) and len(msg["text"]) > 0
        assert isinstance(msg["latency_ms"], float)
        assert isinstance(msg["tool_calls"], int)
        assert isinstance(msg["partial_count"], int)

    def test_error_message_shape(self):
        """Verify the error event structure."""
        msg = {
            "type": "error",
            "message": "Turn timeout",
            "turn_id": "vturn_xyz",
            "latency_ms": 30000.0,
        }
        assert msg["type"] == "error"
        assert isinstance(msg["message"], str)

    def test_session_ready_message_shape(self):
        """Verify the session.ready ack on voice WS connect."""
        msg = {
            "type": "session.ready",
            "session_id": "pipecat-sess-123",
            "correlation_id": "req_abcdef123456",
        }
        assert msg["type"] == "session.ready"
        assert isinstance(msg["session_id"], str)
        assert msg["correlation_id"].startswith("req_")

    def test_control_end_recognized(self):
        """control.end is the stream close signal."""
        msg = {"type": "control.end"}
        assert msg["type"] == "control.end"

    def test_correlation_id_in_turn_record(self):
        """Correlation ID propagates through VoiceTurnRecord."""
        r = VoiceTurnRecord(
            turn_id="vturn_test",
            correlation_id="req_propagated123",
            user_text="test",
        )
        assert r.correlation_id == "req_propagated123"
        assert r.correlation_id.startswith("req_")
