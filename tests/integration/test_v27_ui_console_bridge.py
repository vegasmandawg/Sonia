"""
v2.7 M3 Integration Tests -- UI Console Bridge

Tests the UISessionState, UIStreamManager, and the control ACK
round-trip protocol that the Electron UI expects.

Tests (16):
  UISessionState (5):
    1. Default control values
    2. Toggle valid control succeeds
    3. Toggle invalid control fails
    4. Diagnostics snapshot well-formed
    5. Conversation state tracks

  UIStreamManager (4):
    6. Register connection
    7. Unregister connection
    8. Max connections enforced
    9. Connection count updates

  Control ACK Protocol (7):
    10. control.toggle -> ack.control (valid field)
    11. control.toggle -> nack.control (unknown field)
    12. control.toggle -> nack.control (missing value)
    13. control.interrupt -> ack.interrupt + idle state
    14. control.replay -> ack.replay
    15. control.hold -> ack.control
    16. Unknown message type -> error
"""

import sys
import asyncio
import json

import pytest

sys.path.insert(0, r"S:\services\api-gateway")


# ===========================================================================
# UISessionState tests
# ===========================================================================

class TestUISessionState:

    def test_default_controls(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="test-1")
        assert state.controls["micEnabled"] is True
        assert state.controls["camEnabled"] is False
        assert state.controls["privacyEnabled"] is False
        assert state.controls["holdActive"] is False
        assert state.conversation_state == "idle"
        assert state.emotion == "neutral"

    def test_toggle_valid_control(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="test-2")
        ok, reason = state.toggle_control("micEnabled", False)
        assert ok is True
        assert reason == ""
        assert state.controls["micEnabled"] is False

    def test_toggle_invalid_control(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="test-3")
        ok, reason = state.toggle_control("nonExistent", True)
        assert ok is False
        assert "unknown_field" in reason

    def test_diagnostics_snapshot(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="test-4")
        diag = state.to_diagnostics()
        assert diag["session_id"] == "test-4"
        assert "uptime_seconds" in diag
        assert "latency" in diag
        assert "breaker_states" in diag
        assert "dlq_depth" in diag
        assert "privacy_status" in diag
        assert diag["privacy_status"] == "disabled"  # default

    def test_conversation_state_tracks(self):
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="test-5")
        assert state.conversation_state == "idle"
        state.conversation_state = "speaking"
        assert state.conversation_state == "speaking"


# ===========================================================================
# UIStreamManager tests
# ===========================================================================

class MockWebSocket:
    """Minimal mock WebSocket for testing."""
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = True


class TestUIStreamManager:

    @pytest.mark.asyncio
    async def test_register_connection(self):
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        ws = MockWebSocket()
        state = await mgr.register("conn-1", ws, "sess-1")
        assert state.session_id == "sess-1"
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_unregister_connection(self):
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        ws = MockWebSocket()
        await mgr.register("conn-1", ws, "sess-1")
        assert mgr.connection_count == 1
        await mgr.unregister("conn-1")
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_max_connections(self):
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        mgr.MAX_CONNECTIONS = 2
        ws1, ws2, ws3 = MockWebSocket(), MockWebSocket(), MockWebSocket()
        await mgr.register("c1", ws1, "s1")
        await mgr.register("c2", ws2, "s2")
        with pytest.raises(RuntimeError, match="MAX_UI_CONNECTIONS"):
            await mgr.register("c3", ws3, "s3")

    @pytest.mark.asyncio
    async def test_broadcast(self):
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        ws1, ws2 = MockWebSocket(), MockWebSocket()
        await mgr.register("c1", ws1, "s1")
        await mgr.register("c2", ws2, "s2")
        count = await mgr.broadcast({"type": "test"})
        assert count == 2
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1


# ===========================================================================
# Control ACK Protocol tests
# ===========================================================================

class TestControlAckProtocol:
    """Tests the _dispatch_ui_message logic."""

    @pytest.mark.asyncio
    async def test_toggle_valid_field_ack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-1")
        msg = {"type": "control.toggle", "field": "micEnabled", "value": False}
        await _dispatch_ui_message(ws, state, "control.toggle", msg)
        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "ack.control"
        assert ws.sent[0]["field"] == "micEnabled"
        assert state.controls["micEnabled"] is False

    @pytest.mark.asyncio
    async def test_toggle_unknown_field_nack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-2")
        msg = {"type": "control.toggle", "field": "unknownField", "value": True}
        await _dispatch_ui_message(ws, state, "control.toggle", msg)
        assert ws.sent[0]["type"] == "nack.control"
        assert "unknown_field" in ws.sent[0]["reason"]

    @pytest.mark.asyncio
    async def test_toggle_missing_value_nack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-3")
        msg = {"type": "control.toggle", "field": "micEnabled"}
        await _dispatch_ui_message(ws, state, "control.toggle", msg)
        assert ws.sent[0]["type"] == "nack.control"
        assert "missing" in ws.sent[0]["reason"]

    @pytest.mark.asyncio
    async def test_interrupt_ack_and_idle(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-4")
        state.conversation_state = "speaking"
        await _dispatch_ui_message(ws, state, "control.interrupt", {})
        assert ws.sent[0]["type"] == "ack.interrupt"
        assert state.conversation_state == "idle"

    @pytest.mark.asyncio
    async def test_replay_ack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-5")
        await _dispatch_ui_message(ws, state, "control.replay", {})
        assert ws.sent[0]["type"] == "ack.replay"

    @pytest.mark.asyncio
    async def test_hold_ack(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-6")
        msg = {"type": "control.hold", "active": True}
        await _dispatch_ui_message(ws, state, "control.hold", msg)
        assert ws.sent[0]["type"] == "ack.control"
        assert ws.sent[0]["field"] == "holdActive"
        assert state.controls["holdActive"] is True

    @pytest.mark.asyncio
    async def test_unknown_message_error(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="proto-7")
        await _dispatch_ui_message(ws, state, "bogus.type", {})
        assert ws.sent[0]["type"] == "error"
        assert "unknown" in ws.sent[0]["message"]
