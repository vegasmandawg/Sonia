"""
v2.7 M2 Integration Tests -- Perception Runtime

Tests the EventBus, HttpEventBridge, and PerceptionPipelineRunner.

Tests (20):
  EventBus (8):
    1. Subscribe and publish delivers to handler
    2. Pattern matching with glob wildcard
    3. Multiple subscribers receive same event
    4. Unsubscribe stops delivery
    5. Handler timeout records dead letter
    6. Handler exception records dead letter
    7. Stats are accurate after publish
    8. History bounded to MAX_HISTORY

  HttpEventBridge (3):
    9. Bridge target registration
    10. Bridge stats after registration
    11. Bridge forward failure records error

  PerceptionPipelineRunner (9):
    12. Runner starts and stops cleanly
    13. Cooldown blocks rapid triggers
    14. Busy check blocks concurrent analysis
    15. Privacy disabled blocks analysis
    16. Successful analysis updates stats
    17. Runner config defaults
    18. Stats to_dict is well-formed
    19. Frame event handler increments triggers
    20. Perception request handler uses payload trigger
"""

import sys
import asyncio
import time

import pytest

sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:\services\perception")


# ===========================================================================
# EventBus tests
# ===========================================================================

class TestEventBus:

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self):
        from event_bus import EventBus
        bus = EventBus(name="test")
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler, name="test_handler")
        delivered = await bus.publish({
            "type": "test.event",
            "id": "e1",
            "source": "unit",
            "correlation_id": "req_test",
        })
        assert delivered == 1
        assert len(received) == 1
        assert received[0]["type"] == "test.event"

    @pytest.mark.asyncio
    async def test_glob_pattern_matching(self):
        from event_bus import EventBus
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event["type"])

        bus.subscribe("vision.*", handler)
        await bus.publish({"type": "vision.frame.available", "id": "1"})
        await bus.publish({"type": "vision.privacy.changed", "id": "2"})
        await bus.publish({"type": "perception.completed", "id": "3"})  # no match
        assert received == ["vision.frame.available", "vision.privacy.changed"]

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        from event_bus import EventBus
        bus = EventBus()
        counts = {"a": 0, "b": 0}

        async def handler_a(event):
            counts["a"] += 1

        async def handler_b(event):
            counts["b"] += 1

        bus.subscribe("test.*", handler_a)
        bus.subscribe("test.*", handler_b)
        delivered = await bus.publish({"type": "test.event", "id": "1"})
        assert delivered == 2
        assert counts["a"] == 1
        assert counts["b"] == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        from event_bus import EventBus
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(1)

        sub_id = bus.subscribe("test.*", handler)
        await bus.publish({"type": "test.x", "id": "1"})
        assert len(received) == 1

        removed = bus.unsubscribe(sub_id)
        assert removed is True
        await bus.publish({"type": "test.y", "id": "2"})
        assert len(received) == 1  # no more deliveries

    @pytest.mark.asyncio
    async def test_handler_timeout_dead_letter(self):
        from event_bus import EventBus
        bus = EventBus()
        bus.HANDLER_TIMEOUT_S = 0.1

        async def slow_handler(event):
            await asyncio.sleep(1.0)

        bus.subscribe("test.*", slow_handler)
        await bus.publish({"type": "test.slow", "id": "1", "correlation_id": "req_slow"})
        dead = bus.get_dead_letters()
        assert len(dead) == 1
        assert dead[0]["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_handler_exception_dead_letter(self):
        from event_bus import EventBus
        bus = EventBus()

        async def bad_handler(event):
            raise ValueError("boom")

        bus.subscribe("test.*", bad_handler)
        await bus.publish({"type": "test.bad", "id": "1"})
        dead = bus.get_dead_letters()
        assert len(dead) == 1
        assert "boom" in dead[0]["error"]

    @pytest.mark.asyncio
    async def test_stats_accuracy(self):
        from event_bus import EventBus
        bus = EventBus()

        async def ok_handler(event):
            pass

        bus.subscribe("*", ok_handler)
        await bus.publish({"type": "a", "id": "1"})
        await bus.publish({"type": "b", "id": "2"})
        stats = bus.get_stats()
        assert stats["total_published"] == 2
        assert stats["total_delivered"] == 2
        assert stats["total_failed"] == 0

    @pytest.mark.asyncio
    async def test_history_bounded(self):
        from event_bus import EventBus
        bus = EventBus()
        bus.MAX_HISTORY = 5

        async def noop(event):
            pass

        bus.subscribe("*", noop)
        for i in range(10):
            await bus.publish({"type": "test", "id": str(i)})
        assert len(bus._history) == 5


# ===========================================================================
# HttpEventBridge tests
# ===========================================================================

class TestHttpEventBridge:

    def test_target_registration(self):
        from event_bus import EventBus, HttpEventBridge
        bus = EventBus()
        bridge = HttpEventBridge(bus)
        bridge.register_target(
            name="perception",
            url="http://127.0.0.1:7070/v1/perception/events",
            patterns=["perception.*"],
        )
        assert "perception" in bridge._targets

    def test_bridge_stats(self):
        from event_bus import EventBus, HttpEventBridge
        bus = EventBus()
        bridge = HttpEventBridge(bus)
        bridge.register_target("test", "http://localhost:9999", ["test.*"])
        stats = bridge.get_stats()
        assert "test" in stats["targets"]
        assert stats["total_forwarded"] == 0
        assert stats["total_errors"] == 0

    @pytest.mark.asyncio
    async def test_bridge_forward_failure(self):
        from event_bus import EventBus, HttpEventBridge
        bus = EventBus()
        bridge = HttpEventBridge(bus, timeout=1.0)
        bridge.register_target("bad", "http://127.0.0.1:1/bad", ["test.*"])
        # Publish will try to forward and fail
        await bus.publish({"type": "test.event", "id": "1"})
        assert bridge._total_forward_errors == 1


# ===========================================================================
# PerceptionPipelineRunner tests
# ===========================================================================

class TestPerceptionPipelineRunner:

    def _make_analyze_fn(self, scene_id="scene_test"):
        """Create a mock analyze function."""
        class MockScene:
            def __init__(self):
                self.scene_id = scene_id

        async def analyze_fn(trigger, context, frame_count, correlation_id):
            return MockScene()

        return analyze_fn

    def _make_privacy_fn(self, enabled=True):
        """Create a mock privacy check function."""
        async def privacy_fn():
            return {
                "privacy": "enabled" if enabled else "disabled",
                "capture_allowed": enabled,
            }
        return privacy_fn

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        from pipeline_runner import PerceptionPipelineRunner
        runner = PerceptionPipelineRunner(
            analyze_fn=self._make_analyze_fn(),
            privacy_check_fn=self._make_privacy_fn(),
        )
        await runner.start()
        assert runner.running is True
        await runner.stop()
        assert runner.running is False

    @pytest.mark.asyncio
    async def test_cooldown_blocks_rapid(self):
        from pipeline_runner import PerceptionPipelineRunner, RunnerConfig
        cfg = RunnerConfig(cooldown_s=10.0)
        runner = PerceptionPipelineRunner(
            analyze_fn=self._make_analyze_fn(),
            privacy_check_fn=self._make_privacy_fn(),
            config=cfg,
        )
        await runner.start()
        # First call succeeds
        r1 = await runner.on_frame_event({"type": "vision.frame.available"})
        assert r1["ok"] is True
        # Second call blocked by cooldown
        r2 = await runner.on_frame_event({"type": "vision.frame.available"})
        assert r2["ok"] is False
        assert r2["reason"] == "cooldown"
        assert runner.stats.total_skipped_cooldown == 1
        await runner.stop()

    @pytest.mark.asyncio
    async def test_busy_blocks_concurrent(self):
        from pipeline_runner import PerceptionPipelineRunner, RunnerConfig
        cfg = RunnerConfig(cooldown_s=0.0)

        async def slow_analyze(trigger, context, frame_count, correlation_id):
            await asyncio.sleep(0.5)
            class S:
                scene_id = "slow"
            return S()

        runner = PerceptionPipelineRunner(
            analyze_fn=slow_analyze,
            privacy_check_fn=self._make_privacy_fn(),
            config=cfg,
        )
        await runner.start()

        # Start first analysis
        task = asyncio.create_task(runner.on_frame_event({"type": "test"}))
        await asyncio.sleep(0.05)  # let it start
        # Second should be blocked
        r2 = await runner.on_frame_event({"type": "test"})
        assert r2["ok"] is False
        assert r2["reason"] == "busy"
        await task
        await runner.stop()

    @pytest.mark.asyncio
    async def test_privacy_disabled_blocks(self):
        from pipeline_runner import PerceptionPipelineRunner
        runner = PerceptionPipelineRunner(
            analyze_fn=self._make_analyze_fn(),
            privacy_check_fn=self._make_privacy_fn(enabled=False),
        )
        await runner.start()
        r = await runner.on_frame_event({"type": "test"})
        assert r["ok"] is False
        assert r["reason"] == "privacy_disabled"
        assert runner.stats.total_skipped_privacy == 1
        await runner.stop()

    @pytest.mark.asyncio
    async def test_successful_analysis_updates_stats(self):
        from pipeline_runner import PerceptionPipelineRunner, RunnerConfig
        cfg = RunnerConfig(cooldown_s=0.0)
        runner = PerceptionPipelineRunner(
            analyze_fn=self._make_analyze_fn(scene_id="scene_abc"),
            privacy_check_fn=self._make_privacy_fn(),
            config=cfg,
        )
        await runner.start()
        r = await runner.on_frame_event({"type": "test"})
        assert r["ok"] is True
        assert r["scene_id"] == "scene_abc"
        assert runner.stats.total_runs == 1
        assert runner.stats.last_scene_id == "scene_abc"
        await runner.stop()

    def test_runner_config_defaults(self):
        from pipeline_runner import RunnerConfig
        cfg = RunnerConfig()
        assert cfg.cooldown_s == 5.0
        assert cfg.staleness_s == 10.0
        assert cfg.scheduled_interval_s == 0.0
        assert cfg.max_inference_ms == 2000.0
        assert cfg.frame_count == 1

    def test_stats_to_dict(self):
        from pipeline_runner import RunnerStats
        stats = RunnerStats()
        d = stats.to_dict()
        assert "total_triggers" in d
        assert "total_runs" in d
        assert "total_skipped_cooldown" in d
        assert "uptime_seconds" in d

    @pytest.mark.asyncio
    async def test_frame_event_increments_triggers(self):
        from pipeline_runner import PerceptionPipelineRunner, RunnerConfig
        cfg = RunnerConfig(cooldown_s=0.0)
        runner = PerceptionPipelineRunner(
            analyze_fn=self._make_analyze_fn(),
            privacy_check_fn=self._make_privacy_fn(),
            config=cfg,
        )
        await runner.start()
        await runner.on_frame_event({"type": "test"})
        await runner.on_frame_event({"type": "test"})
        assert runner.stats.total_triggers == 2
        await runner.stop()

    @pytest.mark.asyncio
    async def test_perception_request_uses_payload_trigger(self):
        from pipeline_runner import PerceptionPipelineRunner, RunnerConfig

        captured = {}

        async def capture_analyze(trigger, context, frame_count, correlation_id):
            captured["trigger"] = trigger
            captured["context"] = context
            class S:
                scene_id = "req_scene"
            return S()

        cfg = RunnerConfig(cooldown_s=0.0)
        runner = PerceptionPipelineRunner(
            analyze_fn=capture_analyze,
            privacy_check_fn=self._make_privacy_fn(),
            config=cfg,
        )
        await runner.start()
        r = await runner.on_perception_request({
            "type": "perception.requested",
            "payload": {"trigger": "wake_word", "context": "user said hey sonia"},
            "correlation_id": "req_test123",
        })
        assert r["ok"] is True
        assert captured["trigger"] == "wake_word"
        assert captured["context"] == "user said hey sonia"
        await runner.stop()
