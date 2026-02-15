"""Confirmation storm integrity tests (G21).

Tests:
    1. Storm with rapid concurrent intake
    2. One-shot confirmation consumption
    3. Zero double-consume invariant
    4. Queue cap enforced with deterministic degradation
    5. No orphan tokens after drain
    6. Throttle under backpressure (never auto-approve)
    7. Full pipeline deterministic replay under storm
"""
import pytest

from services.perception.event_normalizer import EventNormalizer
from services.perception.confirmation_batcher import (
    ConfirmationBatcher, MAX_PENDING_CONFIRMATIONS,
)
from services.perception.policy import PerceptionPipeline


# ── Helpers ──────────────────────────────────────────────────────────────

SID = "storm-session"
CID = "corr-storm"
normalizer = EventNormalizer()


def _raw(event_id, object_id=None, confidence=0.9):
    return {
        "event_id": event_id,
        "session_id": SID,
        "source": "vision",
        "event_type": "entity_detection",
        "object_id": object_id or f"obj-{event_id}",
        "summary": object_id or f"summary-{event_id}",
        "confidence": confidence,
        "correlation_id": CID,
        "timestamp": 1000.0,
        "payload": {"recommended_action": "file.read"},
    }


# ── Tests ────────────────────────────────────────────────────────────────

class TestConfirmationStormIntegrity:

    def test_storm_rapid_intake(self):
        """High-rate submission fills batcher without errors."""
        batcher = ConfirmationBatcher(max_pending=50)

        items = []
        for i in range(40):
            env = normalizer.normalize(_raw(f"storm-{i}", object_id=f"obj-{i}"))
            item, throttle = batcher.submit(env, priority=1, action="file.read")
            assert throttle is None, f"Should not throttle at {i}"
            assert item is not None
            items.append(item)

        assert batcher.pending_count == 40
        assert batcher.stats["total_submitted"] == 40

    def test_one_shot_confirmation_consumption(self):
        """Each item can only be confirmed once."""
        batcher = ConfirmationBatcher(max_pending=50)
        env = normalizer.normalize(_raw("oneshot-1", object_id="oneshot"))
        item, _ = batcher.submit(env, priority=1, action="file.read")

        # First confirm succeeds
        result1 = batcher.confirm(item.item_id)
        assert result1["ok"] is True
        assert result1["status"] == "confirmed"

        # Second confirm fails (already consumed)
        result2 = batcher.confirm(item.item_id)
        assert result2["ok"] is False
        assert result2["status"] == "already_consumed"
        assert result2["double_consume"] is True
        assert batcher.stats["double_consume_attempts"] == 1

    def test_zero_double_consume_invariant(self):
        """Multiple confirm/deny attempts on same item never double-consume."""
        batcher = ConfirmationBatcher(max_pending=50)
        env = normalizer.normalize(_raw("dbl-1", object_id="dblobj"))
        item, _ = batcher.submit(env, priority=1, action="file.read")

        # Confirm
        batcher.confirm(item.item_id)

        # Try deny after confirm
        result = batcher.deny(item.item_id, reason="too late")
        assert result["ok"] is False
        assert result["double_consume"] is True

        # Try confirm again
        result2 = batcher.confirm(item.item_id)
        assert result2["ok"] is False
        assert result2["double_consume"] is True

        assert batcher.stats["double_consume_attempts"] == 2

    def test_queue_cap_enforced_with_throttle(self):
        """When pending hits max, new submissions are throttled (never auto-approved)."""
        max_pending = 10
        batcher = ConfirmationBatcher(max_pending=max_pending)

        # Fill to cap
        for i in range(max_pending):
            env = normalizer.normalize(_raw(f"cap-{i}", object_id=f"capobj-{i}"))
            item, throttle = batcher.submit(env, priority=1, action="file.read")
            assert item is not None

        assert batcher.pending_count == max_pending

        # Next submission should be throttled
        env_over = normalizer.normalize(_raw("over-cap", object_id="overcap"))
        item, throttle = batcher.submit(env_over, priority=1, action="file.read")
        assert item is None
        assert throttle is not None
        assert "throttled" in throttle
        assert batcher.stats["total_throttled"] == 1

        # Verify NO auto-approve happened
        assert batcher.stats["total_confirmed"] == 0

    def test_no_orphan_tokens_after_drain(self):
        """After confirming/denying all items, orphan count is 0."""
        batcher = ConfirmationBatcher(max_pending=50)

        item_ids = []
        for i in range(20):
            env = normalizer.normalize(_raw(f"drain-{i}", object_id=f"drainobj-{i}"))
            item, _ = batcher.submit(env, priority=1, action="file.read")
            item_ids.append(item.item_id)

        # Confirm half, deny half
        for i, item_id in enumerate(item_ids):
            if i % 2 == 0:
                batcher.confirm(item_id)
            else:
                batcher.deny(item_id, reason="test")

        assert batcher.get_orphan_count() == 0
        assert batcher.pending_count == 0

    def test_throttle_never_auto_approves(self):
        """Under backpressure, system throttles intake, never auto-approves."""
        pipeline = PerceptionPipeline(
            dedupe_window=200, max_pending=5,
            lane_cap=50, total_cap=150,
        )

        results = []
        for i in range(20):
            raw = _raw(f"bp-{i}", object_id=f"bpobj-{i}")
            result = pipeline.process_raw(raw, action="file.read")
            results.append(result)

        # First 5 should submit, rest should throttle
        submitted = [r for r in results if r.confirmation_item is not None]
        throttled = [r for r in results if r.throttled]

        assert len(submitted) == 5
        assert len(throttled) >= 10  # some may be deduped

        # Zero auto-approves
        report = pipeline.get_report()
        assert report["batcher_stats"]["total_confirmed"] == 0
        assert report["bypass_attempts"] == 0

    def test_full_pipeline_deterministic_replay_under_storm(self):
        """Same storm event stream replayed produces identical provenance hash."""
        events = [_raw(f"replay-{i}", object_id=f"robj-{i}") for i in range(30)]

        hashes = []
        for _ in range(2):
            pipeline = PerceptionPipeline(
                dedupe_window=100, max_pending=50,
                lane_cap=50, total_cap=150,
            )
            for raw in events:
                pipeline.process_raw(raw, action="file.read")
            hashes.append(pipeline.provenance.deterministic_hash())

        assert hashes[0] == hashes[1], "Storm replay must be deterministic"

    def test_bypass_attempt_tracking(self):
        """Attempting to execute unconfirmed item tracks bypass attempt."""
        batcher = ConfirmationBatcher(max_pending=50)
        env = normalizer.normalize(_raw("bypass-1", object_id="bypobj"))
        item, _ = batcher.submit(env, priority=1, action="file.read")

        # Try to validate without confirming
        result = batcher.validate_execution(item.item_id)
        assert result["ok"] is False
        assert result["bypass_attempt"] is True
        assert batcher.stats["bypass_attempts"] == 1

        # Nonexistent item
        result2 = batcher.validate_execution("nonexistent")
        assert result2["ok"] is False
        assert result2["bypass_attempt"] is True
        assert batcher.stats["bypass_attempts"] == 2
