"""Priority routing tests (G20 supplementary).

Tests:
    1. Priority lane assignment correctness
    2. Deterministic ordering inside lane
    3. Weighted fairness under sustained load
    4. Overflow policy correctness and audit emissions
    5. P0 preemption over P1/P2
"""
import pytest

from services.perception.event_normalizer import EventNormalizer, PerceptionEnvelope
from services.perception.priority_router import (
    PriorityRouter,
    assign_priority,
    PRIORITY_P0, PRIORITY_P1, PRIORITY_P2,
    HIGH_CONFIDENCE_THRESHOLD,
)


# ── Helpers ──────────────────────────────────────────────────────────────

SID = "route-session"
CID = "corr-route"
normalizer = EventNormalizer()


def _env(event_id, event_type="entity_detection", confidence=0.9,
         source="vision", recommended_action=None):
    raw = {
        "event_id": event_id,
        "session_id": SID,
        "source": source,
        "event_type": event_type,
        "object_id": f"obj-{event_id}",
        "summary": f"summary-{event_id}",
        "confidence": confidence,
        "correlation_id": CID,
        "timestamp": 1000.0,
        "payload": {},
    }
    if recommended_action:
        raw["payload"]["recommended_action"] = recommended_action
    return normalizer.normalize(raw)


# ── Tests ────────────────────────────────────────────────────────────────

class TestPriorityRouting:

    def test_safety_events_get_p0(self):
        """Safety-critical event types always get P0."""
        env = _env("safety-1", event_type="safety_alert")
        assert assign_priority(env) == PRIORITY_P0

        env2 = _env("emergency-1", event_type="emergency")
        assert assign_priority(env2) == PRIORITY_P0

    def test_high_confidence_gets_p1(self):
        """High-confidence events with actions get P1."""
        env = _env("action-1", confidence=0.95, recommended_action="file.read")
        assert assign_priority(env) == PRIORITY_P1

    def test_low_confidence_gets_p2(self):
        """Low-confidence events without actions get P2."""
        env = _env("info-1", confidence=0.3, event_type="entity_detection")
        assert assign_priority(env) == PRIORITY_P2

    def test_informational_events_get_p2(self):
        """Informational event types always get P2."""
        env = _env("ambient-1", event_type="ambient_update")
        assert assign_priority(env) == PRIORITY_P2

    def test_deterministic_ordering_within_lane(self):
        """Events routed to the same lane maintain insertion order."""
        router = PriorityRouter(lane_cap=50)
        envelopes = [_env(f"ord-{i}", confidence=0.95,
                          recommended_action="act") for i in range(5)]

        for env in envelopes:
            router.route(env)

        drained = router.drain(max_items=5)
        ids = [env.event_id for _, env in drained]
        assert ids == [f"ord-{i}" for i in range(5)]

    def test_weighted_fairness_p1_p2(self):
        """P1 gets ~3x more drain slots than P2 in weighted round-robin."""
        router = PriorityRouter(lane_cap=50)

        # Add 12 P1 and 12 P2 events
        for i in range(12):
            router.route(_env(f"p1-{i}", confidence=0.95, recommended_action="act"))
        for i in range(12):
            router.route(_env(f"p2-{i}", confidence=0.3))

        drained = router.drain(max_items=16)
        p1_count = sum(1 for p, _ in drained if p == PRIORITY_P1)
        p2_count = sum(1 for p, _ in drained if p == PRIORITY_P2)

        # With 3:1 ratio over 16 items: expect ~12 P1 and ~4 P2
        assert p1_count >= 10, f"P1 should get majority: got {p1_count}"
        assert p2_count >= 2, f"P2 should get some: got {p2_count}"

    def test_overflow_policy_and_audit(self):
        """When queue overflows, lowest priority evicted first with audit."""
        router = PriorityRouter(lane_cap=5, total_cap=10)

        # Fill P2 lane to cap (5 items)
        for i in range(5):
            router.route(_env(f"fill-p2-{i}", confidence=0.3))

        # Fill P1 lane to cap (5 items) -- total now at 10
        for i in range(5):
            router.route(_env(f"fill-p1-{i}", confidence=0.95, recommended_action="act"))

        assert router.total_queued == 10

        # Add P1 event -- should evict from P2
        _, overflow = router.route(_env("overflow-p1", confidence=0.95,
                                        recommended_action="act"))

        assert overflow is not None
        assert overflow.action_taken == "coalesce_lowest"
        assert overflow.reason == "queue_cap_exceeded"
        assert len(router.overflow_log) == 1
        assert router.stats["total_overflow"] == 1

    def test_p0_preemption_in_drain(self):
        """P0 events are always drained before P1/P2."""
        router = PriorityRouter(lane_cap=50)

        # Add P1 first
        router.route(_env("p1-first", confidence=0.95, recommended_action="act"))
        # Then P0
        router.route(_env("p0-second", event_type="safety_alert"))

        drained = router.drain(max_items=5)
        # P0 should come first despite being added second
        assert drained[0][0] == PRIORITY_P0
        assert drained[0][1].event_id == "p0-second"
