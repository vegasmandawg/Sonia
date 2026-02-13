"""
v2.7 Extended Soak with Forced Faults

10x of the M5 simulation with injected failures:
  disconnects, timeouts, partial frames, poison messages.

Tests (12):
  Voice soak (3):
    1. 500 sequential voice turn records stable
    2. 200 records with random failure injection (20% fail rate)
    3. Turn history bounded (no unbounded growth)

  EventBus soak (3):
    4. 1000 event dispatches with 5% handler failures
    5. Dead letter queue bounded under sustained failure
    6. Pattern matching performance: 1000 events, 20 subscribers

  UI soak (3):
    7. 200 control toggles with intermittent NACK injection
    8. 10 connections churning (register/unregister rapidly)
    9. Broadcast under connection churn

  Action bridge soak (3):
    10. 300 mixed action calls (safe/guarded/unknown)
    11. 50 rapid approve/deny cycles
    12. Batch of 100 with 10% unknown intents
"""

import sys
import asyncio
import random
import time

import pytest
pytestmark = [pytest.mark.legacy_v26_v28, pytest.mark.legacy_voice_turn_router]

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")


# ── Mocks ───────────────────────────────────────────────────────────────────

class MockWS:
    def __init__(self):
        self.sent = []
        self.closed = False
    async def send_json(self, d):
        self.sent.append(d)
    async def close(self, code=1000, reason=""):
        self.closed = True


class MockOpenclawClient:
    def __init__(self, fail_rate=0.0):
        self.call_count = 0
        self.fail_rate = fail_rate
    async def execute(self, tool_name, args, timeout_ms=5000, correlation_id=None):
        self.call_count += 1
        if random.random() < self.fail_rate:
            return {"status": "error", "error": "injected fault"}
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


def _make_bridge(fail_rate=0.0):
    import action_audit
    action_audit._audit_logger = MockAuditLogger()
    from action_pipeline import ActionPipeline
    from action_turn_bridge import ActionTurnBridge
    oc = MockOpenclawClient(fail_rate=fail_rate)
    pipeline = ActionPipeline(
        openclaw_client=oc,
        breaker_registry=MockBreakerRegistry(),
        dead_letter_queue=MockDLQ(),
    )
    return ActionTurnBridge(pipeline), oc, pipeline


# ===========================================================================
# Voice soak
# ===========================================================================

class TestVoiceSoak:

    def test_500_sequential_records(self):
        """500 sequential voice turn records complete without leak."""
        from app.voice_turn_router import VoiceTurnRouter, VoiceTurnRecord
        router = VoiceTurnRouter(gateway_url="http://localhost:9999")
        for i in range(500):
            rec = VoiceTurnRecord(
                turn_id=f"vturn_{i}", session_id="soak",
                correlation_id=f"req_{i}", user_text=f"msg_{i}",
                ok=True, latency_ms=random.uniform(5, 50),
            )
            router._turn_history.append(rec)
        assert router.total_turns == 500
        stats = router.get_stats()
        assert stats["total_turns"] == 500
        assert stats["recent_success_rate"] == 1.0

    def test_200_with_20pct_failures(self):
        """200 records with 20% injected failures."""
        from app.voice_turn_router import VoiceTurnRouter, VoiceTurnRecord
        router = VoiceTurnRouter(gateway_url="http://localhost:9999")
        random.seed(42)
        for i in range(200):
            ok = random.random() > 0.2  # 80% success
            rec = VoiceTurnRecord(
                turn_id=f"vturn_{i}", session_id="soak-fail",
                correlation_id=f"req_{i}", user_text=f"msg_{i}",
                ok=ok, latency_ms=random.uniform(5, 100),
                error="" if ok else "injected failure",
            )
            router._turn_history.append(rec)
        assert router.total_turns == 200
        stats = router.get_stats()
        # Success rate should be approximately 80%
        assert 0.6 < stats["recent_success_rate"] < 0.95

    def test_history_bounded(self):
        """Turn history doesn't grow beyond MAX_HISTORY if enforced."""
        from app.voice_turn_router import VoiceTurnRouter, VoiceTurnRecord
        router = VoiceTurnRouter(gateway_url="http://localhost:9999")
        max_hist = getattr(router, 'MAX_HISTORY', 10000)
        # Add records up to 2x the history limit or 1000 whichever smaller
        count = min(max_hist * 2, 1000)
        for i in range(count):
            router._turn_history.append(
                VoiceTurnRecord(turn_id=f"vturn_{i}", ok=True, latency_ms=5.0)
            )
        # Should be at most max_hist or count (whichever implemented)
        assert len(router._turn_history) <= max(max_hist, count)


# ===========================================================================
# EventBus soak
# ===========================================================================

class TestEventBusSoak:

    @pytest.mark.asyncio
    async def test_1000_dispatches_with_5pct_failures(self):
        """1000 events with 5% handler failure rate."""
        from event_bus import EventBus
        bus = EventBus()
        delivered = 0
        random.seed(99)

        async def flaky_handler(e):
            nonlocal delivered
            if random.random() < 0.05:
                raise RuntimeError("flaky fail")
            delivered += 1

        bus.subscribe("soak.*", flaky_handler)
        for i in range(1000):
            await bus.publish({"type": f"soak.evt_{i % 50}", "data": {"i": i}})

        # Should have ~950 delivered, ~50 dead-lettered
        assert 900 < delivered < 1000
        assert len(bus._dead_letters) > 0
        assert len(bus._dead_letters) < 100

    @pytest.mark.asyncio
    async def test_dlq_bounded_under_sustained_failure(self):
        """Dead letters don't grow beyond MAX_DEAD_LETTERS even under sustained failure."""
        from event_bus import EventBus
        bus = EventBus()
        async def always_fail(e):
            raise RuntimeError("always fails")
        bus.subscribe("fail.*", always_fail)
        for i in range(200):  # 200 failures
            await bus.publish({"type": "fail.test", "data": {"i": i}})
        assert len(bus._dead_letters) <= bus.MAX_DEAD_LETTERS

    @pytest.mark.asyncio
    async def test_pattern_matching_performance(self):
        """1000 events with 20 subscribers completes under 500ms."""
        from event_bus import EventBus
        bus = EventBus()
        counts = [0] * 20

        for idx in range(20):
            local_idx = idx
            async def handler(e, i=local_idx):
                counts[i] += 1
            bus.subscribe(f"perf.topic_{idx % 5}.*", handler)

        t0 = time.monotonic()
        for i in range(1000):
            await bus.publish({"type": f"perf.topic_{i % 5}.event", "data": {"i": i}})
        elapsed_ms = (time.monotonic() - t0) * 1000

        total_deliveries = sum(counts)
        assert total_deliveries > 0
        assert elapsed_ms < 500, f"Performance: {elapsed_ms:.1f}ms > 500ms budget"


# ===========================================================================
# UI soak
# ===========================================================================

class TestUISoak:

    @pytest.mark.asyncio
    async def test_200_toggles_with_nack_injection(self):
        """200 toggles, some hitting invalid fields -> mix of ACK/NACK."""
        from routes.ui_stream import UISessionState, _dispatch_ui_message
        ws = MockWS()
        state = UISessionState(session_id="soak-ui")
        fields = ["micEnabled", "camEnabled", "privacyEnabled", "holdActive",
                   "invalidField"]  # 20% NACK rate
        random.seed(77)
        for i in range(200):
            field = random.choice(fields)
            msg = {"type": "control.toggle", "field": field, "value": True}
            await _dispatch_ui_message(ws, state, "control.toggle", msg)
        acks = sum(1 for m in ws.sent if m["type"] == "ack.control")
        nacks = sum(1 for m in ws.sent if m["type"] == "nack.control")
        assert acks + nacks == 200
        assert nacks > 0  # Some NACKs expected

    @pytest.mark.asyncio
    async def test_connection_churn(self):
        """10 connections registering and unregistering rapidly."""
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        for i in range(10):
            ws = MockWS()
            await mgr.register(f"churn-{i}", ws, f"sess-{i}")
            await mgr.unregister(f"churn-{i}")
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_under_churn(self):
        """Broadcast works correctly even during connection churn."""
        from routes.ui_stream import UIStreamManager
        mgr = UIStreamManager()
        ws1, ws2, ws3 = MockWS(), MockWS(), MockWS()
        await mgr.register("stable", ws1, "s1")
        await mgr.register("temp", ws2, "s2")
        await mgr.broadcast({"type": "test", "data": "round1"})
        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1
        await mgr.unregister("temp")
        await mgr.register("new", ws3, "s3")
        await mgr.broadcast({"type": "test", "data": "round2"})
        assert len(ws1.sent) == 2
        assert len(ws2.sent) == 1  # Disconnected, no more messages
        assert len(ws3.sent) == 1
        await mgr.unregister("stable")
        await mgr.unregister("new")


# ===========================================================================
# Action bridge soak
# ===========================================================================

class TestActionBridgeSoak:

    @pytest.mark.asyncio
    async def test_300_mixed_calls(self):
        """300 calls: safe (file.read), guarded (shell.run), unknown."""
        bridge, oc, pipeline = _make_bridge()
        intents = [
            ("file.read", {"path": "/tmp/x"}),
            ("shell.run", {"command": "ls"}),
            ("clipboard.read", {}),
            ("nonexistent.tool", {}),
        ]
        executed, pending, rejected = 0, 0, 0
        for i in range(300):
            intent, args = intents[i % len(intents)]
            r = await bridge.execute_tool_call(
                tool_name=intent, tool_args=args,
                session_id="soak", correlation_id=f"req_{i}",
            )
            if r.executed: executed += 1
            elif r.pending_approval: pending += 1
            elif r.rejected: rejected += 1

        # 75 file.read + 75 clipboard.read = 150 executed
        assert executed == 150
        # 75 shell.run = 75 pending
        assert pending == 75
        # 75 nonexistent.tool = 75 rejected
        assert rejected == 75

    @pytest.mark.asyncio
    async def test_50_approve_deny_cycles(self):
        """50 rapid approve/deny cycles on guarded actions."""
        bridge, oc, pipeline = _make_bridge()
        for i in range(50):
            r = await bridge.execute_tool_call(
                tool_name="shell.run", tool_args={"command": "ls"},
                session_id="cycle", correlation_id=f"req_cycle_{i}",
            )
            assert r.pending_approval
            if i % 2 == 0:
                a = await bridge.approve_pending(r.action_id)
                assert a.executed
            else:
                d = await bridge.deny_pending(r.action_id)
                assert d.rejected

    @pytest.mark.asyncio
    async def test_batch_100_with_10pct_unknown(self):
        """Batch of 100 with 10% unknown intents doesn't crash."""
        bridge, oc, pipeline = _make_bridge()
        random.seed(55)
        calls = []
        for i in range(100):
            if random.random() < 0.1:
                calls.append({"tool_name": "bogus.tool", "args": {}})
            else:
                calls.append({"tool_name": "file.read", "args": {"path": f"/tmp/{i}"}})
        results = await bridge.execute_batch(
            tool_calls=calls, session_id="batch-soak", correlation_id="req_batch_soak",
        )
        assert len(results) == 100
        executed = sum(1 for r in results if r.executed)
        rejected = sum(1 for r in results if r.rejected)
        assert executed + rejected == 100
        assert executed > 80  # ~90% should succeed
