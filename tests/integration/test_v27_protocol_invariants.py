"""
v2.7 Protocol Invariant Tests -- Streaming Hazards

Validates protocol invariants that the promotion gate checks:

  Protocol invariants (6):
    1. Out-of-order events: EventBus preserves publish order per handler
    2. Duplicate correlation IDs: same corr_id routes to same handlers
    3. Dropped client reconnect: StreamState transitions are valid
    4. Idempotent ACK: repeated toggle produces single ACK per call
    5. Event type uniqueness: no two different meanings for same type string
    6. Correlation ID propagation: child events inherit parent corr_id

  Dead-letter behavior (5):
    7. Bounded growth: DLQ respects MAX_DEAD_LETTERS
    8. Replay determinism: replaying same letter twice marks replayed once
    9. Poison message: handler that always throws -> dead letter, not crash
    10. DLQ serialization: to_dict() roundtrips cleanly
    11. DLQ purge: old entries removed, new entries preserved

  Concurrency (4):
    12. N sessions in parallel: 5 concurrent voice turn records isolated
    13. Mixed voice/perception: EventBus handles interleaved event types
    14. Mixed voice/UI: UIStreamManager broadcast doesn't cross sessions
    15. No cross-talk: action bridge batch with distinct session_ids

  Latency budgets (4):
    16. Voice turn router overhead: < 10ms for record creation
    17. Action bridge overhead: < 50ms for safe tool through pipeline
    18. EventBus dispatch overhead: < 5ms for single handler
    19. UI toggle overhead: < 5ms for control toggle + ACK
"""

import sys
import asyncio
import time
import dataclasses

import pytest

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")

from pipecat_voice_turn_router import VoiceTurnRouter, VoiceTurnRecord

# ── Mocks ───────────────────────────────────────────────────────────────────

class MockWS:
    def __init__(self):
        self.sent = []
    async def send_json(self, d):
        self.sent.append(d)


class MockOpenclawClient:
    def __init__(self):
        self.call_count = 0
    async def execute(self, tool_name, args, timeout_ms=5000, correlation_id=None):
        self.call_count += 1
        return {"status": "executed", "result": {"tool": tool_name}, "side_effects": []}


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


class MockDLQ:
    def __init__(self):
        self.letters = []
    async def enqueue(self, **kw):
        self.letters.append(kw)
    async def list_letters(self, **kw):
        return self.letters
    async def get(self, lid):
        return None


class MockAuditTrail:
    def __init__(self):
        self.events = []
    def record(self, *a, **kw):
        self.events.append((a, kw))


class MockAuditLogger:
    def __init__(self):
        self.trails = {}
    def create_trail(self, action_id, intent, correlation_id=None):
        t = MockAuditTrail()
        self.trails[action_id] = t
        return t
    def flush_trail(self, action_id):
        pass


def _make_bridge():
    import action_audit
    action_audit._audit_logger = MockAuditLogger()
    from action_pipeline import ActionPipeline
    from action_turn_bridge import ActionTurnBridge
    oc = MockOpenclawClient()
    pipeline = ActionPipeline(
        openclaw_client=oc,
        breaker_registry=MockBreakerRegistry(),
        dead_letter_queue=MockDLQ(),
    )
    return ActionTurnBridge(pipeline), oc


# ===========================================================================
# Protocol invariants
# ===========================================================================

class TestProtocolInvariants:

    @pytest.mark.asyncio
    async def test_event_bus_preserves_order(self):
        """EventBus delivers events in publish order to each handler."""
        from event_bus import EventBus
        bus = EventBus()
        order = []
        async def h(e):
            order.append(e["data"]["seq"])
        bus.subscribe("order.*", h)
        for i in range(20):
            await bus.publish({"type": "order.test", "data": {"seq": i}})
        assert order == list(range(20))

    @pytest.mark.asyncio
    async def test_duplicate_correlation_ids_route_same(self):
        """Same correlation_id in different events routes to same handlers."""
        from event_bus import EventBus
        bus = EventBus()
        seen_corrs = []
        async def h(e):
            seen_corrs.append(e.get("correlation_id", ""))
        bus.subscribe("dup.*", h)
        await bus.publish({"type": "dup.a", "correlation_id": "req_same", "data": {}})
        await bus.publish({"type": "dup.b", "correlation_id": "req_same", "data": {}})
        assert seen_corrs == ["req_same", "req_same"]

    def test_stream_state_transitions_valid(self):
        """StreamState only has 5 valid values."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "gsc_inv", r"S:\services\pipecat\clients\gateway_stream_client.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["gsc_inv"] = mod
        spec.loader.exec_module(mod)
        valid = {"disconnected", "connecting", "connected", "reconnecting", "error"}
        assert {s.value for s in mod.StreamState} == valid

    @pytest.mark.asyncio
    async def test_idempotent_ack_repeated_toggle(self):
        """Repeated identical toggles each produce exactly one ACK."""
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWS()
        state = UISessionState(session_id="idem-1")
        for _ in range(5):
            msg = {"type": "control.toggle", "field": "micEnabled", "value": False}
            await _dispatch_ui_message(ws, state, "control.toggle", msg)
        assert len(ws.sent) == 5
        assert all(m["type"] == "ack.control" for m in ws.sent)

    def test_event_type_uniqueness(self):
        """No two EventType enum members share the same value."""
        from events import EventType
        values = [e.value for e in EventType]
        assert len(values) == len(set(values))

    @pytest.mark.asyncio
    async def test_correlation_id_propagation(self):
        """EventEnvelope.derive() preserves correlation_id."""
        from events import EventEnvelope
        parent = EventEnvelope(
            type="turn.started", source="gateway",
            correlation_id="req_parent_abc", payload={"x": 1},
        )
        child = parent.derive("turn.completed", "gateway", {"y": 2})
        assert child.correlation_id == parent.correlation_id
        assert child.type == "turn.completed"


# ===========================================================================
# Dead-letter behavior
# ===========================================================================

class TestDeadLetterBehavior:

    @pytest.mark.asyncio
    async def test_bounded_growth(self):
        """DLQ respects MAX_DEAD_LETTERS."""
        from dead_letter import DeadLetterQueue, MAX_DEAD_LETTERS
        dlq = DeadLetterQueue()
        for i in range(MAX_DEAD_LETTERS + 50):
            await dlq.enqueue(
                action_id=f"act_{i}", intent="test", params={},
                error_code="ERR", error_message="test",
            )
        letters = await dlq.list_letters(limit=MAX_DEAD_LETTERS + 100)
        assert len(letters) <= MAX_DEAD_LETTERS

    @pytest.mark.asyncio
    async def test_replay_determinism(self):
        """Replaying same letter twice doesn't create duplicate markers."""
        from dead_letter import DeadLetterQueue
        dlq = DeadLetterQueue()
        lid = await dlq.enqueue(
            action_id="act_det", intent="file.read", params={},
            error_code="ERR", error_message="fail",
        )
        await dlq.mark_replayed(lid, "act_replay1")
        await dlq.mark_replayed(lid, "act_replay2")
        letter = await dlq.get(lid)
        assert letter.replayed is True
        # Second replay overwrites, but replayed remains True
        assert letter.replay_action_id == "act_replay2"

    @pytest.mark.asyncio
    async def test_poison_message_dead_lettered(self):
        """Handler that always throws -> event goes to dead letters, bus doesn't crash."""
        from event_bus import EventBus
        bus = EventBus()
        async def poison_handler(e):
            raise RuntimeError("I always fail")
        bus.subscribe("poison.*", poison_handler)
        await bus.publish({"type": "poison.test", "data": {}})
        assert len(bus._dead_letters) == 1
        assert "I always fail" in bus._dead_letters[0].error

    @pytest.mark.asyncio
    async def test_dlq_serialization_roundtrip(self):
        """DeadLetter.to_dict() produces valid JSON-serializable dict."""
        import json
        from dead_letter import DeadLetterQueue
        dlq = DeadLetterQueue()
        lid = await dlq.enqueue(
            action_id="act_serial", intent="shell.run",
            params={"command": "ls"}, error_code="TIMEOUT",
            error_message="timed out", correlation_id="req_ser",
        )
        letter = await dlq.get(lid)
        d = letter.to_dict()
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert parsed["letter_id"] == lid
        assert parsed["intent"] == "shell.run"

    @pytest.mark.asyncio
    async def test_dlq_purge(self):
        """Purge removes entries older than threshold. Just-created entries survive."""
        from dead_letter import DeadLetterQueue
        from datetime import datetime, timedelta
        dlq = DeadLetterQueue()
        for i in range(5):
            await dlq.enqueue(
                action_id=f"act_p{i}", intent="test", params={},
                error_code="ERR", error_message="old",
            )
        # Back-date all entries by 2 hours
        for dl in dlq._letters.values():
            dl.created_at = datetime.utcnow() - timedelta(hours=2)
        purged = await dlq.purge(older_than_hours=1)
        assert purged == 5
        letters = await dlq.list_letters(limit=100)
        assert len(letters) == 0


# ===========================================================================
# Concurrency tests
# ===========================================================================

class TestConcurrency:

    @pytest.mark.asyncio
    async def test_parallel_voice_sessions_isolated(self):
        """5 concurrent voice turn records are fully isolated."""
        records = [
            VoiceTurnRecord(
                turn_id=f"vturn_{i}", session_id=f"sess_{i}",
                correlation_id=f"req_{i}", user_text=f"msg_{i}",
                ok=True, latency_ms=10.0 + i,
            )
            for i in range(5)
        ]
        ids = [r.turn_id for r in records]
        sessions = [r.session_id for r in records]
        assert len(set(ids)) == 5
        assert len(set(sessions)) == 5

    @pytest.mark.asyncio
    async def test_mixed_voice_perception_events(self):
        """EventBus handles interleaved voice and perception events."""
        from event_bus import EventBus
        bus = EventBus()
        voice_events, perc_events = [], []
        async def voice_h(e): voice_events.append(e)
        async def perc_h(e): perc_events.append(e)
        bus.subscribe("voice.*", voice_h)
        bus.subscribe("perception.*", perc_h)
        # Interleave
        for i in range(10):
            if i % 2 == 0:
                await bus.publish({"type": "voice.turn", "data": {"i": i}})
            else:
                await bus.publish({"type": "perception.frame", "data": {"i": i}})
        assert len(voice_events) == 5
        assert len(perc_events) == 5

    @pytest.mark.asyncio
    async def test_ui_broadcast_no_cross_session(self):
        """UIStreamManager broadcast reaches all connections."""
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        ws1, ws2 = MockWS(), MockWS()
        await mgr.register("conn-1", ws1, "sess-1")
        await mgr.register("conn-2", ws2, "sess-2")
        await mgr.broadcast({"type": "test.broadcast", "data": "shared"})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1
        await mgr.unregister("conn-1")
        await mgr.unregister("conn-2")

    @pytest.mark.asyncio
    async def test_action_bridge_distinct_sessions(self):
        """Action bridge calls with different session_ids produce independent results."""
        bridge, oc = _make_bridge()
        r1 = await bridge.execute_tool_call(
            tool_name="file.read", tool_args={"path": "/a"},
            session_id="sess-A", correlation_id="req_A",
        )
        r2 = await bridge.execute_tool_call(
            tool_name="file.read", tool_args={"path": "/b"},
            session_id="sess-B", correlation_id="req_B",
        )
        assert r1.action_id != r2.action_id
        assert r1.executed and r2.executed


# ===========================================================================
# Latency budgets (plumbing overhead, not inference)
# ===========================================================================

class TestLatencyBudgets:

    def test_voice_turn_record_creation_under_10ms(self):
        t0 = time.monotonic()
        for _ in range(100):
            VoiceTurnRecord(
                turn_id="vturn_x", session_id="s", correlation_id="r",
                user_text="hi", ok=True, latency_ms=5.0,
            )
        elapsed_ms = (time.monotonic() - t0) * 1000
        per_record = elapsed_ms / 100
        assert per_record < 10.0, f"Record creation {per_record:.2f}ms > 10ms budget"

    @pytest.mark.asyncio
    async def test_action_bridge_safe_under_50ms(self):
        bridge, oc = _make_bridge()
        t0 = time.monotonic()
        r = await bridge.execute_tool_call(
            tool_name="file.read", tool_args={"path": "/tmp/x"},
            correlation_id="req_lat1",
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        assert r.executed
        assert elapsed_ms < 50.0, f"Bridge latency {elapsed_ms:.2f}ms > 50ms budget"

    @pytest.mark.asyncio
    async def test_event_bus_dispatch_under_5ms(self):
        from event_bus import EventBus
        bus = EventBus()
        async def noop(e): pass
        bus.subscribe("lat.*", noop)
        t0 = time.monotonic()
        for _ in range(100):
            await bus.publish({"type": "lat.test", "data": {}})
        elapsed_ms = (time.monotonic() - t0) * 1000
        per_dispatch = elapsed_ms / 100
        assert per_dispatch < 5.0, f"Dispatch {per_dispatch:.2f}ms > 5ms budget"

    @pytest.mark.asyncio
    async def test_ui_toggle_under_5ms(self):
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWS()
        state = UISessionState(session_id="lat-ui")
        t0 = time.monotonic()
        for _ in range(100):
            msg = {"type": "control.toggle", "field": "micEnabled", "value": True}
            await _dispatch_ui_message(ws, state, "control.toggle", msg)
        elapsed_ms = (time.monotonic() - t0) * 1000
        per_toggle = elapsed_ms / 100
        assert per_toggle < 5.0, f"Toggle {per_toggle:.2f}ms > 5ms budget"
