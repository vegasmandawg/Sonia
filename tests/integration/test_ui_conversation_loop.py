"""
Integration tests for Phase 2: UI Conversation Loop

Tests the end-to-end flow from WebSocket input.text through the turn pipeline
and back to the UI client. Covers:
- Session establishment
- Text input validation
- Turn pipeline bridge (user echo, state transitions, response/error)
- Concurrency guard
- Diagnostics with real latency data
- Control messages still work alongside text input
- Connection limits
"""

import asyncio
import json
import os
import sys
import time
import uuid
import pytest

# Ensure gateway module path
sys.path.insert(0, r"S:\services\api-gateway")

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

try:
    import websockets
except ImportError:
    pytest.skip("websockets not installed", allow_module_level=True)


WS_URL = "ws://127.0.0.1:7000/v1/ui/stream"
CONNECT_TIMEOUT = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def connect_and_get_session(url=WS_URL, timeout=CONNECT_TIMEOUT):
    """Connect to UI stream and return (ws, session_id)."""
    ws = await websockets.connect(url, open_timeout=timeout)
    # Read until session.created
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
        msg = json.loads(raw)
        if msg.get("type") == "session.created":
            return ws, msg.get("session_id", "")
    raise TimeoutError("No session.created received")


async def recv_type(ws, msg_type: str, timeout: float = 30.0):
    """Receive messages until the specified type appears."""
    collected = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            msg = json.loads(raw)
            collected.append(msg)
            if msg.get("type") == msg_type:
                return msg, collected
        except asyncio.TimeoutError:
            break
    return None, collected


async def recv_until_idle(ws, timeout: float = 35.0):
    """Receive all messages until state.conversation returns to idle."""
    msgs = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            msg = json.loads(raw)
            msgs.append(msg)
            if msg.get("type") == "state.conversation" and msg.get("state") == "idle":
                return msgs
        except asyncio.TimeoutError:
            break
    return msgs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestUIConversationLoop:
    """Tests for the input.text -> turn pipeline -> response flow."""

    @pytest.mark.asyncio
    async def test_session_created_on_connect(self):
        """T1: Connecting to /v1/ui/stream yields session.created with a session_id."""
        ws, session_id = await connect_and_get_session()
        try:
            assert session_id, "session_id should be non-empty"
            assert session_id.startswith("ui-"), f"session_id should start with 'ui-', got: {session_id}"
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_empty_input_rejected(self):
        """T2: Empty input.text returns an error."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send(json.dumps({"type": "input.text", "text": ""}))
            msg, _ = await recv_type(ws, "error", timeout=5)
            assert msg is not None, "Should receive an error"
            assert "empty_input_text" in msg.get("message", "")
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_whitespace_only_input_rejected(self):
        """T2b: Whitespace-only input.text returns an error."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send(json.dumps({"type": "input.text", "text": "   \n\t  "}))
            msg, _ = await recv_type(ws, "error", timeout=5)
            assert msg is not None, "Should receive an error"
            assert "empty_input_text" in msg.get("message", "")
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_turn_user_echo(self):
        """T3: input.text echoes back turn.user with the original text."""
        ws, _ = await connect_and_get_session()
        try:
            test_text = f"Test message {uuid.uuid4().hex[:8]}"
            await ws.send(json.dumps({"type": "input.text", "text": test_text}))
            msg, _ = await recv_type(ws, "turn.user", timeout=5)
            assert msg is not None, "Should receive turn.user"
            assert msg.get("text") == test_text
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_state_transitions(self):
        """T4: input.text triggers thinking state, then returns to idle."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send(json.dumps({"type": "input.text", "text": "Hello"}))
            msgs = await recv_until_idle(ws, timeout=35)

            types = [m.get("type") for m in msgs]
            states = [
                m.get("state")
                for m in msgs
                if m.get("type") == "state.conversation"
            ]

            assert "thinking" in states, f"Should transition to thinking. States: {states}"
            assert states[-1] == "idle", f"Should return to idle. States: {states}"
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_turn_response_or_error(self):
        """T5: After input.text, receive either turn.assistant or error (depending on backend)."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send(json.dumps({"type": "input.text", "text": "What is 2+2?"}))
            msgs = await recv_until_idle(ws, timeout=35)

            types = [m.get("type") for m in msgs]
            has_assistant = any(m.get("type") == "turn.assistant" for m in msgs)
            has_error = any(m.get("type") == "error" for m in msgs)

            assert has_assistant or has_error, (
                f"Should receive turn.assistant or error. Types: {types}"
            )
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_turn_in_progress_guard(self):
        """T6: Sending input.text while a turn is in progress returns turn_in_progress error."""
        ws, _ = await connect_and_get_session()
        try:
            # Send first message to start a turn
            await ws.send(json.dumps({"type": "input.text", "text": "First"}))
            # Wait for thinking state
            await recv_type(ws, "state.conversation", timeout=5)

            # Send second message while first is processing
            await ws.send(json.dumps({"type": "input.text", "text": "Second"}))

            # Look for turn_in_progress error
            deadline = time.time() + 10
            found = False
            while time.time() < deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    msg = json.loads(raw)
                    if msg.get("type") == "error" and "turn_in_progress" in msg.get("message", ""):
                        found = True
                        break
                except asyncio.TimeoutError:
                    break

            assert found, "Should receive turn_in_progress error"
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_diagnostics_push(self):
        """T7: Diagnostics are pushed periodically with correct structure."""
        ws, session_id = await connect_and_get_session()
        try:
            msg, _ = await recv_type(ws, "diagnostics", timeout=8)
            assert msg is not None, "Should receive diagnostics within 8s"
            data = msg.get("data", {})

            # Verify required fields
            assert "session_id" in data
            assert data["session_id"] == session_id
            assert "uptime_seconds" in data
            assert "turn_count" in data
            assert "latency" in data
            assert "privacy_status" in data
            assert "last_turn_id" in data
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_diagnostics_latency_structure(self):
        """T8: Diagnostics latency contains expected sub-fields."""
        ws, _ = await connect_and_get_session()
        try:
            msg, _ = await recv_type(ws, "diagnostics", timeout=8)
            assert msg is not None
            latency = msg.get("data", {}).get("latency", {})

            for key in ["asr_ms", "model_ms", "tool_ms", "memory_ms", "total_ms"]:
                assert key in latency, f"Missing latency key: {key}"
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_control_toggle_still_works(self):
        """T9: Control toggles still work alongside text input."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send(json.dumps({
                "type": "control.toggle",
                "field": "micEnabled",
                "value": False,
            }))
            msg, _ = await recv_type(ws, "ack.control", timeout=5)
            assert msg is not None
            assert msg.get("field") == "micEnabled"
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_unknown_message_type(self):
        """T10: Unknown message types return error."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send(json.dumps({"type": "foo.bar"}))
            msg, _ = await recv_type(ws, "error", timeout=5)
            assert msg is not None
            assert "unknown_message_type" in msg.get("message", "")
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_invalid_json_rejected(self):
        """T11: Invalid JSON returns error."""
        ws, _ = await connect_and_get_session()
        try:
            await ws.send("not valid json {{{")
            msg, _ = await recv_type(ws, "error", timeout=5)
            assert msg is not None
            assert "invalid_json" in msg.get("message", "")
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_turn_count_increments(self):
        """T12: After a text turn completes, diagnostics show incremented turn_count."""
        ws, _ = await connect_and_get_session()
        try:
            # Send a message and wait for full turn to complete
            await ws.send(json.dumps({"type": "input.text", "text": "Count test"}))
            await recv_until_idle(ws, timeout=35)

            # Wait for next diagnostics push
            msg, _ = await recv_type(ws, "diagnostics", timeout=8)
            assert msg is not None
            data = msg.get("data", {})
            assert data.get("turn_count", 0) >= 1, (
                f"turn_count should be >= 1 after a turn, got: {data.get('turn_count')}"
            )
        finally:
            await ws.close()

    @pytest.mark.asyncio
    async def test_multiple_sequential_turns(self):
        """T13: Can send multiple turns sequentially (each after previous completes)."""
        ws, _ = await connect_and_get_session()
        try:
            for i in range(2):
                await ws.send(json.dumps({"type": "input.text", "text": f"Turn {i+1}"}))
                msgs = await recv_until_idle(ws, timeout=35)
                types = [m.get("type") for m in msgs]
                assert "turn.user" in types, f"Turn {i+1}: should echo turn.user"
        finally:
            await ws.close()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-x"]))
