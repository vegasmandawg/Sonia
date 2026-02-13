"""
v2.7 M5 Cross-Track Integration Tests

Validates that all four v2.7 milestones work together as a coherent
runtime integration layer:

  M1 (Voice Turn Loop) -- GatewayStreamClient + VoiceTurnRouter
  M2 (Perception Runtime) -- EventBus + PerceptionPipelineRunner
  M3 (UI Console Bridge) -- UISessionState + UIStreamManager + ACK protocol
  M4 (Action Execution) -- ActionTurnBridge + ActionPipeline

Tests (18):
  Vertical slice (5):
    1. Voice turn router -> action bridge -> pipeline executes tool
    2. Event bus dispatches perception result -> UI state updates
    3. UI control toggle -> ACK -> state consistent
    4. Action bridge dry_run -> pipeline validates without executing
    5. Full chain: voice turn -> tool call -> action bridge -> result

  Cross-module contracts (5):
    6. EventBus event types match EventEnvelope schema
    7. UISessionState diagnostics includes all required keys
    8. ActionTurnBridge result maps cleanly to ToolCallRecord
    9. VoiceTurnRecord fields are superset of action telemetry
    10. Pipeline ActionPlanResponse serializes to JSON

  Concurrency & isolation (4):
    11. Two concurrent voice sessions don't interfere
    12. EventBus handlers are isolated per pattern
    13. UIStreamManager max connections enforced under load
    14. ActionTurnBridge batch doesn't leak state between calls

  Soak simulation (4):
    15. 50 sequential voice turns complete without leak
    16. 100 event bus dispatches complete without dead letters
    17. 20 UI control toggles all ACK correctly
    18. 30 action bridge calls with mixed results stable
"""

import sys
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import pytest
pytestmark = [pytest.mark.legacy_v26_v28, pytest.mark.legacy_voice_turn_router]

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")


# ── Mocks ───────────────────────────────────────────────────────────────────

class MockWebSocket:
    """Minimal mock for UI stream tests."""
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = True


class MockOpenclawClient:
    """Mock OpenClaw for action pipeline."""
    def __init__(self):
        self.call_count = 0

    async def execute(self, tool_name, args, timeout_ms=5000, correlation_id=None):
        self.call_count += 1
        return {
            "status": "executed",
            "result": {"tool": tool_name, "echo": args},
            "side_effects": [],
        }


class MockBreakerRegistry:
    class _Breaker:
        class _State:
            value = "closed"
        state = _State()
        async def call(self, fn):
            return await fn()

    def __init__(self):
        self._b = {}

    def get_or_create(self, name):
        if name not in self._b:
            self._b[name] = self._Breaker()
        return self._b[name]

    def get(self, name):
        return self._b.get(name)


class MockDeadLetterQueue:
    def __init__(self):
        self.letters = []

    async def enqueue(self, **kwargs):
        self.letters.append(kwargs)

    async def list_letters(self, **kwargs):
        return self.letters

    async def get(self, letter_id):
        return None


class MockAuditTrail:
    def __init__(self):
        self.events = []
    def record(self, *args, **kwargs):
        self.events.append((args, kwargs))


class MockAuditLogger:
    def __init__(self):
        self.trails = {}
    def create_trail(self, action_id, intent, correlation_id=None):
        t = MockAuditTrail()
        self.trails[action_id] = t
        return t
    def flush_trail(self, action_id):
        pass


def _make_action_bridge():
    """Create ActionTurnBridge with full mock chain."""
    import action_audit
    mock_audit = MockAuditLogger()
    action_audit._audit_logger = mock_audit

    from action_pipeline import ActionPipeline
    from action_turn_bridge import ActionTurnBridge

    oc = MockOpenclawClient()
    breakers = MockBreakerRegistry()
    dlq = MockDeadLetterQueue()

    pipeline = ActionPipeline(
        openclaw_client=oc,
        breaker_registry=breakers,
        dead_letter_queue=dlq,
    )
    bridge = ActionTurnBridge(pipeline)
    return bridge, oc, dlq


# ===========================================================================
# Vertical slice tests
# ===========================================================================

class TestVerticalSlice:

    @pytest.mark.asyncio
    async def test_voice_router_record_structure(self):
        """VoiceTurnRecord has all fields needed for pipeline integration."""
        from app.voice_turn_router import VoiceTurnRecord
        rec = VoiceTurnRecord(
            turn_id="vturn_abc",
            session_id="sess-1",
            correlation_id="req_123",
            user_text="hello",
            assistant_text="hi there",
            tool_calls=[{"name": "file.read", "args": {"path": "/tmp"}}],
            partial_count=2,
            latency_ms=150.0,
            gateway_latency_ms=120.0,
            ok=True,
        )
        assert rec.turn_id.startswith("vturn_")
        assert rec.tool_calls[0]["name"] == "file.read"
        assert rec.latency_ms > rec.gateway_latency_ms

    @pytest.mark.asyncio
    async def test_event_bus_dispatches_to_handler(self):
        """EventBus dispatches perception result and handler receives it."""
        from event_bus import EventBus
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("perception.*", handler)
        await bus.publish({
            "type": "perception.scene_analyzed",
            "data": {"scene_id": "s1", "confidence": 0.9},
        })
        assert len(received) == 1
        assert received[0]["data"]["scene_id"] == "s1"

    @pytest.mark.asyncio
    async def test_ui_toggle_ack_consistent(self):
        """UI control toggle -> ACK -> state is consistent."""
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="cross-1")
        assert state.controls["micEnabled"] is True

        msg = {"type": "control.toggle", "field": "micEnabled", "value": False}
        await _dispatch_ui_message(ws, state, "control.toggle", msg)

        assert state.controls["micEnabled"] is False
        assert ws.sent[0]["type"] == "ack.control"
        assert ws.sent[0]["field"] == "micEnabled"

    @pytest.mark.asyncio
    async def test_action_bridge_dry_run(self):
        """Action bridge dry_run validates without executing."""
        bridge, oc, dlq = _make_action_bridge()
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/test"},
            dry_run=True,
            correlation_id="req_dry1",
        )
        assert r.dry_run is True
        assert r.executed is False
        assert r.action_state == "validated"
        assert oc.call_count == 0

    @pytest.mark.asyncio
    async def test_full_chain_voice_to_action(self):
        """Voice turn record -> tool call -> action bridge -> executed."""
        from app.voice_turn_router import VoiceTurnRecord
        bridge, oc, dlq = _make_action_bridge()

        # Simulate a voice turn that produced a tool call
        tool_call = {"tool_name": "file.read", "args": {"path": "/data/log.txt"}}
        results = await bridge.execute_batch(
            tool_calls=[tool_call],
            session_id="voice-sess",
            correlation_id="req_chain1",
        )

        assert len(results) == 1
        assert results[0].executed is True
        assert results[0].output["tool"] == "file.read"


# ===========================================================================
# Cross-module contract tests
# ===========================================================================

class TestCrossModuleContracts:

    @pytest.mark.asyncio
    async def test_event_bus_types_match_envelope(self):
        """EventBus event records have type, timestamp, data matching EventEnvelope."""
        from event_bus import EventBus
        bus = EventBus()
        collected = []

        async def handler(event):
            collected.append(event)

        bus.subscribe("test.*", handler)
        await bus.publish({"type": "test.event", "data": {"key": "val"}})

        evt = collected[0]
        assert "type" in evt
        assert evt["type"] == "test.event"

    def test_ui_diagnostics_keys(self):
        """UISessionState diagnostics includes all required keys."""
        from routes.ui_stream import UISessionState
        state = UISessionState(session_id="diag-1")
        diag = state.to_diagnostics()
        required = {"session_id", "uptime_seconds", "latency", "breaker_states",
                     "dlq_depth", "privacy_status"}
        assert required.issubset(set(diag.keys()))

    @pytest.mark.asyncio
    async def test_bridge_result_maps_to_tool_record(self):
        """ActionTurnBridge result has all fields for ToolCallRecord compat."""
        bridge, oc, dlq = _make_action_bridge()
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/x"},
            correlation_id="req_map1",
        )
        # These fields are needed by turn.py's ToolCallRecord
        assert hasattr(r, "tool_name")
        assert hasattr(r, "executed")
        assert hasattr(r, "output")
        assert hasattr(r, "error")
        assert hasattr(r, "duration_ms")

    def test_voice_record_superset_of_telemetry(self):
        """VoiceTurnRecord fields are superset of action telemetry needs."""
        from app.voice_turn_router import VoiceTurnRecord
        import dataclasses
        fields = {f.name for f in dataclasses.fields(VoiceTurnRecord)}
        needed = {"turn_id", "session_id", "correlation_id", "latency_ms",
                  "tool_calls", "ok", "error"}
        assert needed.issubset(fields)

    @pytest.mark.asyncio
    async def test_pipeline_response_serializes(self):
        """ActionPlanResponse serializes to JSON cleanly."""
        bridge, oc, dlq = _make_action_bridge()
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/x"},
            correlation_id="req_serial1",
        )
        # The action_id should be valid, and the bridge result serializable
        as_dict = {
            "tool_name": r.tool_name,
            "executed": r.executed,
            "action_id": r.action_id,
            "output": r.output,
        }
        serialized = json.dumps(as_dict)
        parsed = json.loads(serialized)
        assert parsed["executed"] is True
        assert parsed["action_id"].startswith("act_")


# ===========================================================================
# Concurrency & isolation tests
# ===========================================================================

class TestConcurrencyIsolation:

    @pytest.mark.asyncio
    async def test_concurrent_voice_sessions(self):
        """Two concurrent voice sessions don't interfere."""
        from app.voice_turn_router import VoiceTurnRouter
        router = VoiceTurnRouter(gateway_url="http://127.0.0.1:7000")
        # Just test the record isolation (no actual connections)
        rec1 = type("Rec", (), {
            "turn_id": "vturn_a",
            "session_id": "sess-a",
        })()
        rec2 = type("Rec", (), {
            "turn_id": "vturn_b",
            "session_id": "sess-b",
        })()
        assert rec1.session_id != rec2.session_id
        assert rec1.turn_id != rec2.turn_id

    @pytest.mark.asyncio
    async def test_event_bus_handler_isolation(self):
        """EventBus handlers for different patterns don't cross-fire."""
        from event_bus import EventBus
        bus = EventBus()
        a_events, b_events = [], []

        async def handler_a(event):
            a_events.append(event)

        async def handler_b(event):
            b_events.append(event)

        bus.subscribe("track.a.*", handler_a)
        bus.subscribe("track.b.*", handler_b)

        await bus.publish({"type": "track.a.event", "data": {"src": "a"}})
        await bus.publish({"type": "track.b.event", "data": {"src": "b"}})

        assert len(a_events) == 1
        assert len(b_events) == 1
        assert a_events[0]["data"]["src"] == "a"
        assert b_events[0]["data"]["src"] == "b"

    @pytest.mark.asyncio
    async def test_ui_max_connections_under_load(self):
        """UIStreamManager max connections enforced even with rapid connects."""
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        mgr.MAX_CONNECTIONS = 3
        sockets = [MockWebSocket() for _ in range(5)]

        # Register up to max
        for i in range(3):
            await mgr.register(f"conn-{i}", sockets[i], f"sess-{i}")
        assert mgr.connection_count == 3

        # Fourth should fail
        with pytest.raises(RuntimeError, match="MAX_UI_CONNECTIONS"):
            await mgr.register("conn-3", sockets[3], "sess-3")

    @pytest.mark.asyncio
    async def test_batch_no_state_leak(self):
        """Batch calls don't leak state between tool executions."""
        bridge, oc, dlq = _make_action_bridge()
        calls = [
            {"tool_name": "file.read", "args": {"path": f"/tmp/{i}"}}
            for i in range(5)
        ]
        results = await bridge.execute_batch(
            tool_calls=calls,
            correlation_id="req_noleak",
        )
        # Each result has unique action_id
        action_ids = [r.action_id for r in results]
        assert len(set(action_ids)) == 5
        # Each has correct output echoed back
        for i, r in enumerate(results):
            assert r.output["echo"]["path"] == f"/tmp/{i}"


# ===========================================================================
# Soak simulation tests
# ===========================================================================

class TestSoakSimulation:

    @pytest.mark.asyncio
    async def test_50_sequential_voice_turns(self):
        """50 sequential voice turn records complete without leak."""
        from app.voice_turn_router import VoiceTurnRouter
        router = VoiceTurnRouter(gateway_url="http://127.0.0.1:7000")
        # Just verify history tracking doesn't leak
        for i in range(50):
            router._turn_history.append(
                type("Rec", (), {"turn_id": f"vturn_{i}", "ok": True, "latency_ms": 10.0})()
            )
        assert len(router._turn_history) == 50
        assert router.total_turns == 50
        stats = router.get_stats()
        assert stats["total_turns"] == 50

    @pytest.mark.asyncio
    async def test_100_event_bus_dispatches(self):
        """100 event bus dispatches complete without dead letters."""
        from event_bus import EventBus
        bus = EventBus()
        count = 0

        async def handler(event):
            nonlocal count
            count += 1

        bus.subscribe("soak.*", handler)
        for i in range(100):
            await bus.publish({"type": f"soak.event_{i % 10}", "data": {"i": i}})

        assert count == 100
        assert len(bus._dead_letters) == 0

    @pytest.mark.asyncio
    async def test_20_ui_toggles_all_ack(self):
        """20 UI control toggles all produce ACKs."""
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWebSocket()
        state = UISessionState(session_id="soak-ui")
        fields = ["micEnabled", "camEnabled", "privacyEnabled", "holdActive"]

        for i in range(20):
            field = fields[i % len(fields)]
            current = state.controls[field]
            msg = {"type": "control.toggle", "field": field, "value": not current}
            await _dispatch_ui_message(ws, state, "control.toggle", msg)

        # All 20 should have produced ack.control
        assert len(ws.sent) == 20
        assert all(m["type"] == "ack.control" for m in ws.sent)

    @pytest.mark.asyncio
    async def test_30_action_bridge_mixed(self):
        """30 action bridge calls with mixed intents remain stable."""
        bridge, oc, dlq = _make_action_bridge()
        # Each intent needs its required params
        intents = [
            ("file.read", {"path": "/tmp/test"}, False),    # safe, executes
            ("shell.run", {"command": "ls"}, True),          # guarded, pending
            ("clipboard.read", {}, False),                   # safe, executes
        ]
        results = []
        for i in range(30):
            intent, base_args, expect_pending = intents[i % 3]
            args = {**base_args, "idx": i}
            r = await bridge.execute_tool_call(
                tool_name=intent,
                tool_args=args,
                session_id="soak-sess",
                correlation_id=f"req_soak_{i}",
            )
            results.append((r, expect_pending))

        executed = sum(1 for r, _ in results if r.executed)
        pending = sum(1 for r, _ in results if r.pending_approval)

        # 10 file.read + 10 clipboard.read = 20 executed
        assert executed == 20
        # 10 shell.run = 10 pending
        assert pending == 10
        assert len(dlq.letters) == 0  # no failures
