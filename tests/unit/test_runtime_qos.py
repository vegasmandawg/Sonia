"""v3.7 M3 — Runtime QoS Engine Tests.

Validates:
- SLO tier configuration (4 tiers)
- Latency recording and SLO violation detection
- Timeout recording
- Turn QoS annotation generation
- Percentile calculation
- Violation log bounded
- Stats accuracy
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join("S:", os.sep, "services", "api-gateway"))

from runtime_qos import (
    SLOTier,
    QoSViolationType,
    SLOTarget,
    LatencyRecord,
    QoSViolation,
    TurnQoSAnnotation,
    RuntimeQoSEngine,
    DEFAULT_SLO_TARGETS,
)


class TestSLOConfiguration(unittest.TestCase):
    """Default SLO targets must cover all 4 tiers."""

    def test_four_tiers(self):
        self.assertEqual(len(DEFAULT_SLO_TARGETS), 4)

    def test_interactive_tier(self):
        t = DEFAULT_SLO_TARGETS[SLOTier.INTERACTIVE.value]
        self.assertEqual(t.p95_ms, 500)

    def test_standard_tier(self):
        t = DEFAULT_SLO_TARGETS[SLOTier.STANDARD.value]
        self.assertEqual(t.p95_ms, 2000)

    def test_batch_tier(self):
        t = DEFAULT_SLO_TARGETS[SLOTier.BATCH.value]
        self.assertEqual(t.p95_ms, 10000)

    def test_all_tiers_have_p50_p95_p99(self):
        for tier in SLOTier:
            t = DEFAULT_SLO_TARGETS[tier.value]
            self.assertGreater(t.p50_ms, 0)
            self.assertGreater(t.p95_ms, t.p50_ms)
            self.assertGreaterEqual(t.p99_ms, t.p95_ms)


class TestLatencyRecording(unittest.TestCase):
    """Latency must be recorded and checked against SLO."""

    def setUp(self):
        self.engine = RuntimeQoSEngine()

    def test_within_slo_no_violation(self):
        record = self.engine.record_latency("turn", 100, SLOTier.STANDARD.value)
        self.assertFalse(record.violated_slo)
        self.assertEqual(record.violation_type, "")

    def test_exceeding_slo_violation(self):
        record = self.engine.record_latency("turn", 3000, SLOTier.STANDARD.value)
        self.assertTrue(record.violated_slo)
        self.assertEqual(record.violation_type, QoSViolationType.LATENCY_EXCEEDED.value)

    def test_record_has_operation_and_tier(self):
        record = self.engine.record_latency("memory_read", 50, SLOTier.INTERACTIVE.value)
        self.assertEqual(record.operation, "memory_read")
        self.assertEqual(record.tier, SLOTier.INTERACTIVE.value)

    def test_correlation_id_preserved(self):
        record = self.engine.record_latency(
            "turn", 100, SLOTier.STANDARD.value, correlation_id="req_123")
        self.assertEqual(record.correlation_id, "req_123")

    def test_record_to_dict(self):
        record = self.engine.record_latency("turn", 100, SLOTier.STANDARD.value)
        d = record.to_dict()
        self.assertIn("operation", d)
        self.assertIn("tier", d)
        self.assertIn("duration_ms", d)
        self.assertIn("violated_slo", d)


class TestTimeoutRecording(unittest.TestCase):
    """Timeouts must be recorded as violations."""

    def setUp(self):
        self.engine = RuntimeQoSEngine()

    def test_timeout_creates_violation(self):
        violation = self.engine.record_timeout("model_call", 5000, SLOTier.STANDARD.value)
        self.assertEqual(violation.violation_type, QoSViolationType.TIMEOUT.value)

    def test_timeout_also_records_latency(self):
        self.engine.record_timeout("model_call", 5000, SLOTier.STANDARD.value)
        stats = self.engine.get_stats()
        self.assertEqual(stats["total_operations"], 1)

    def test_timeout_violation_logged(self):
        self.engine.record_timeout("model_call", 5000, SLOTier.STANDARD.value)
        violations = self.engine.get_violations()
        self.assertGreaterEqual(len(violations), 1)
        self.assertEqual(violations[0]["violation_type"], QoSViolationType.TIMEOUT.value)


class TestTurnAnnotation(unittest.TestCase):
    """Turn annotations must be deterministic."""

    def setUp(self):
        self.engine = RuntimeQoSEngine()

    def test_annotation_within_slo(self):
        ann = self.engine.annotate_turn("turn_001", SLOTier.STANDARD.value, 500)
        self.assertTrue(ann.slo_met)
        self.assertEqual(ann.turn_id, "turn_001")
        self.assertEqual(len(ann.violations), 0)

    def test_annotation_exceeding_slo(self):
        ann = self.engine.annotate_turn("turn_002", SLOTier.STANDARD.value, 3000)
        self.assertFalse(ann.slo_met)
        self.assertGreater(len(ann.violations), 0)

    def test_annotation_with_breakdown(self):
        breakdown = {"memory_read_ms": 100, "model_ms": 800, "tool_ms": 200}
        ann = self.engine.annotate_turn(
            "turn_003", SLOTier.STANDARD.value, 1100, latency_breakdown=breakdown)
        self.assertEqual(ann.latency_breakdown["model_ms"], 800)

    def test_annotation_to_dict(self):
        ann = self.engine.annotate_turn("turn_004", SLOTier.STANDARD.value, 500)
        d = ann.to_dict()
        self.assertIn("turn_id", d)
        self.assertIn("slo_met", d)
        self.assertIn("total_ms", d)

    def test_annotation_deterministic(self):
        ann1 = self.engine.annotate_turn("t", SLOTier.STANDARD.value, 1000)
        ann2 = self.engine.annotate_turn("t", SLOTier.STANDARD.value, 1000)
        self.assertEqual(ann1.slo_met, ann2.slo_met)
        self.assertEqual(len(ann1.violations), len(ann2.violations))


class TestPercentileCalculation(unittest.TestCase):
    """Percentile calculation must be accurate."""

    def setUp(self):
        self.engine = RuntimeQoSEngine()

    def test_empty_history_returns_zeros(self):
        p = self.engine.get_percentiles()
        self.assertEqual(p["count"], 0)
        self.assertEqual(p["p50"], 0.0)

    def test_percentiles_from_data(self):
        for i in range(100):
            self.engine.record_latency("turn", float(i + 1), SLOTier.STANDARD.value)
        p = self.engine.get_percentiles()
        self.assertEqual(p["count"], 100)
        self.assertGreater(p["p50"], 0)
        self.assertGreater(p["p95"], p["p50"])

    def test_filter_by_operation(self):
        self.engine.record_latency("turn", 100, SLOTier.STANDARD.value)
        self.engine.record_latency("action", 200, SLOTier.STANDARD.value)
        p = self.engine.get_percentiles(operation="turn")
        self.assertEqual(p["count"], 1)

    def test_filter_by_tier(self):
        self.engine.record_latency("turn", 100, SLOTier.STANDARD.value)
        self.engine.record_latency("turn", 200, SLOTier.INTERACTIVE.value)
        p = self.engine.get_percentiles(tier=SLOTier.INTERACTIVE.value)
        self.assertEqual(p["count"], 1)


class TestViolationLog(unittest.TestCase):
    """Violation log must be bounded and queryable."""

    def test_violation_recorded(self):
        engine = RuntimeQoSEngine()
        engine.record_latency("turn", 3000, SLOTier.STANDARD.value)
        violations = engine.get_violations()
        self.assertEqual(len(violations), 1)

    def test_violation_to_dict(self):
        engine = RuntimeQoSEngine()
        engine.record_latency("turn", 3000, SLOTier.STANDARD.value, correlation_id="req_1")
        v = engine.get_violations()[0]
        self.assertIn("violation_type", v)
        self.assertIn("observed_value", v)
        self.assertIn("threshold", v)

    def test_violation_limit(self):
        engine = RuntimeQoSEngine()
        for i in range(10):
            engine.record_latency(f"op_{i}", 3000, SLOTier.STANDARD.value)
        violations = engine.get_violations(limit=5)
        self.assertEqual(len(violations), 5)


class TestEngineStats(unittest.TestCase):
    """Engine stats must reflect current state."""

    def test_initial_stats(self):
        engine = RuntimeQoSEngine()
        stats = engine.get_stats()
        self.assertEqual(stats["total_operations"], 0)
        self.assertEqual(stats["total_violations"], 0)
        self.assertEqual(stats["tier_count"], 4)

    def test_stats_after_operations(self):
        engine = RuntimeQoSEngine()
        engine.record_latency("turn", 100, SLOTier.STANDARD.value)
        engine.record_latency("turn", 3000, SLOTier.STANDARD.value)
        stats = engine.get_stats()
        self.assertEqual(stats["total_operations"], 2)
        self.assertEqual(stats["total_violations"], 1)

    def test_slo_table_exposed(self):
        engine = RuntimeQoSEngine()
        table = engine.get_slo_table()
        self.assertEqual(len(table), 4)
        self.assertIn("tier", table[0])
        self.assertIn("p95_ms", table[0])

    def test_history_bounded(self):
        engine = RuntimeQoSEngine(max_history=10)
        for i in range(20):
            engine.record_latency("turn", float(i), SLOTier.STANDARD.value)
        self.assertLessEqual(engine.get_stats()["history_size"], 10)


if __name__ == "__main__":
    unittest.main()
