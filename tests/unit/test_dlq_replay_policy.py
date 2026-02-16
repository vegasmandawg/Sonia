"""v3.7 M2 — DLQ Replay Policy Engine Tests.

Validates:
- Replay decision evaluation (6 ordered checks)
- Dry-run vs real-run state mutation
- Cooldown and budget enforcement
- Manual block/unblock
- Correlation lineage tracking
- Trace immutability and bounded growth
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join("S:", os.sep, "services", "api-gateway"))

from dlq_replay_policy import (
    ReplayDecision,
    RejectReason,
    ReplayTrace,
    CorrelationLineage,
    DLQReplayPolicyEngine,
    NON_RETRYABLE_CLASSES,
)


class TestReplayDecisionEnum(unittest.TestCase):
    """ReplayDecision enum must have exactly 3 outcomes."""

    def test_three_decisions(self):
        self.assertEqual(len(ReplayDecision), 3)

    def test_values(self):
        self.assertEqual(ReplayDecision.APPROVE.value, "approve")
        self.assertEqual(ReplayDecision.REJECT.value, "reject")
        self.assertEqual(ReplayDecision.DEFER.value, "defer")


class TestRejectReasonEnum(unittest.TestCase):
    """RejectReason enum must have 6 reasons."""

    def test_six_reasons(self):
        self.assertEqual(len(RejectReason), 6)

    def test_already_replayed(self):
        self.assertEqual(RejectReason.ALREADY_REPLAYED.value, "already_replayed")


class TestIdempotencyCheck(unittest.TestCase):
    """Already-replayed letters must be rejected."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine()

    def test_already_replayed_rejected(self):
        trace = self.engine.evaluate(
            letter_id="dl_001", already_replayed=True,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_1",
        )
        self.assertEqual(trace.decision, ReplayDecision.REJECT.value)
        self.assertEqual(trace.reject_reason, RejectReason.ALREADY_REPLAYED.value)

    def test_not_replayed_not_rejected_for_idempotency(self):
        trace = self.engine.evaluate(
            letter_id="dl_002", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_2",
        )
        self.assertNotEqual(trace.reject_reason, RejectReason.ALREADY_REPLAYED.value)


class TestNonRetryableCheck(unittest.TestCase):
    """Non-retryable failure classes must be rejected."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine()

    def test_circuit_open_rejected(self):
        trace = self.engine.evaluate(
            letter_id="dl_010", already_replayed=False,
            failure_class="circuit_open", error_code="E503",
            correlation_id="corr_10",
        )
        self.assertEqual(trace.decision, ReplayDecision.REJECT.value)
        self.assertEqual(trace.reject_reason, RejectReason.FAILURE_CLASS_NON_RETRYABLE.value)

    def test_policy_denied_rejected(self):
        trace = self.engine.evaluate(
            letter_id="dl_011", already_replayed=False,
            failure_class="policy_denied", error_code="E403",
            correlation_id="corr_11",
        )
        self.assertEqual(trace.decision, ReplayDecision.REJECT.value)

    def test_validation_failed_rejected(self):
        trace = self.engine.evaluate(
            letter_id="dl_012", already_replayed=False,
            failure_class="validation_failed", error_code="E400",
            correlation_id="corr_12",
        )
        self.assertEqual(trace.decision, ReplayDecision.REJECT.value)

    def test_retryable_class_not_rejected(self):
        trace = self.engine.evaluate(
            letter_id="dl_013", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_13",
        )
        self.assertNotEqual(trace.reject_reason, RejectReason.FAILURE_CLASS_NON_RETRYABLE.value)

    def test_non_retryable_set_complete(self):
        self.assertEqual(len(NON_RETRYABLE_CLASSES), 3)
        self.assertIn("circuit_open", NON_RETRYABLE_CLASSES)
        self.assertIn("policy_denied", NON_RETRYABLE_CLASSES)
        self.assertIn("validation_failed", NON_RETRYABLE_CLASSES)


class TestCircuitBreakerCheck(unittest.TestCase):
    """Open breaker state must defer replay."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine()

    def test_open_breaker_defers(self):
        trace = self.engine.evaluate(
            letter_id="dl_020", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_20", breaker_state="open",
        )
        self.assertEqual(trace.decision, ReplayDecision.DEFER.value)
        self.assertEqual(trace.reject_reason, RejectReason.CIRCUIT_STILL_OPEN.value)

    def test_closed_breaker_passes(self):
        trace = self.engine.evaluate(
            letter_id="dl_021", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_21", breaker_state="closed",
        )
        self.assertNotEqual(trace.reject_reason, RejectReason.CIRCUIT_STILL_OPEN.value)


class TestCooldownCheck(unittest.TestCase):
    """Per-letter cooldown must defer rapid replays."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine(replay_cooldown_seconds=0.05)

    def test_first_replay_approved(self):
        trace = self.engine.evaluate(
            letter_id="dl_030", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_30", dry_run=False,
        )
        self.assertEqual(trace.decision, ReplayDecision.APPROVE.value)

    def test_immediate_replay_deferred(self):
        self.engine.evaluate(
            letter_id="dl_031", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_31a", dry_run=False,
        )
        trace = self.engine.evaluate(
            letter_id="dl_031", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_31b",
        )
        self.assertEqual(trace.decision, ReplayDecision.DEFER.value)
        self.assertEqual(trace.reject_reason, RejectReason.COOLDOWN_ACTIVE.value)

    def test_cooldown_expires(self):
        self.engine.evaluate(
            letter_id="dl_032", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_32a", dry_run=False,
        )
        time.sleep(0.06)
        trace = self.engine.evaluate(
            letter_id="dl_032", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_32b", dry_run=False,
        )
        self.assertEqual(trace.decision, ReplayDecision.APPROVE.value)


class TestBudgetCheck(unittest.TestCase):
    """Window budget must defer when exhausted."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine(
            replay_cooldown_seconds=0.0,
            max_replays_per_window=3,
            window_seconds=300.0,
        )

    def test_within_budget_approved(self):
        for i in range(3):
            trace = self.engine.evaluate(
                letter_id=f"dl_04{i}", already_replayed=False,
                failure_class="execution_error", error_code="E500",
                correlation_id=f"corr_04{i}", dry_run=False,
            )
            self.assertEqual(trace.decision, ReplayDecision.APPROVE.value)

    def test_over_budget_deferred(self):
        for i in range(3):
            self.engine.evaluate(
                letter_id=f"dl_05{i}", already_replayed=False,
                failure_class="execution_error", error_code="E500",
                correlation_id=f"corr_05{i}", dry_run=False,
            )
        trace = self.engine.evaluate(
            letter_id="dl_053", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_053",
        )
        self.assertEqual(trace.decision, ReplayDecision.DEFER.value)
        self.assertEqual(trace.reject_reason, RejectReason.BUDGET_EXHAUSTED.value)


class TestDryRunIsolation(unittest.TestCase):
    """Dry-run must never mutate engine state."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine(replay_cooldown_seconds=0.0)

    def test_dry_run_no_cooldown_set(self):
        self.engine.evaluate(
            letter_id="dl_060", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_60", dry_run=True,
        )
        # Second call should also approve (no cooldown was set)
        trace = self.engine.evaluate(
            letter_id="dl_060", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_60b", dry_run=True,
        )
        self.assertEqual(trace.decision, ReplayDecision.APPROVE.value)

    def test_dry_run_no_budget_consumed(self):
        engine = DLQReplayPolicyEngine(
            replay_cooldown_seconds=0.0,
            max_replays_per_window=2,
        )
        for i in range(5):
            engine.evaluate(
                letter_id=f"dl_07{i}", already_replayed=False,
                failure_class="execution_error", error_code="E500",
                correlation_id=f"corr_07{i}", dry_run=True,
            )
        # All should still approve since dry_run doesn't consume budget
        trace = engine.evaluate(
            letter_id="dl_075", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_075", dry_run=True,
        )
        self.assertEqual(trace.decision, ReplayDecision.APPROVE.value)


class TestManualBlock(unittest.TestCase):
    """Manual block/unblock must override normal evaluation."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine()

    def test_blocked_letter_rejected(self):
        self.engine.block_letter("dl_080")
        trace = self.engine.evaluate(
            letter_id="dl_080", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_80",
        )
        self.assertEqual(trace.decision, ReplayDecision.REJECT.value)
        self.assertEqual(trace.reject_reason, RejectReason.MANUAL_BLOCK.value)

    def test_unblocked_letter_approved(self):
        self.engine.block_letter("dl_081")
        self.engine.unblock_letter("dl_081")
        trace = self.engine.evaluate(
            letter_id="dl_081", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_81",
        )
        self.assertEqual(trace.decision, ReplayDecision.APPROVE.value)

    def test_unblock_nonexistent_safe(self):
        self.engine.unblock_letter("nonexistent")  # should not raise


class TestCorrelationLineage(unittest.TestCase):
    """Correlation lineage must track original -> replay chains."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine()

    def test_record_lineage_creates_entry(self):
        lineage = self.engine.record_lineage("corr_orig", "act_orig")
        self.assertEqual(lineage.original_correlation_id, "corr_orig")
        self.assertEqual(lineage.original_action_id, "act_orig")
        self.assertEqual(lineage.status, "pending")

    def test_add_replay_updates_lineage(self):
        self.engine.record_lineage("corr_orig", "act_orig")
        lineage = self.engine.record_lineage("corr_orig", "act_orig", "corr_replay1", "act_replay1")
        self.assertEqual(len(lineage.replay_correlation_ids), 1)
        self.assertEqual(lineage.status, "replayed")

    def test_get_lineage_returns_dict(self):
        self.engine.record_lineage("corr_orig", "act_orig")
        result = self.engine.get_lineage("act_orig")
        self.assertIsNotNone(result)
        self.assertEqual(result["original_correlation_id"], "corr_orig")
        self.assertEqual(result["replay_count"], 0)

    def test_get_lineage_missing_returns_none(self):
        result = self.engine.get_lineage("nonexistent")
        self.assertIsNone(result)


class TestTraceManagement(unittest.TestCase):
    """Traces must be bounded and queryable."""

    def setUp(self):
        self.engine = DLQReplayPolicyEngine()

    def test_trace_recorded(self):
        self.engine.evaluate(
            letter_id="dl_100", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_100",
        )
        traces = self.engine.get_traces()
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["letter_id"], "dl_100")

    def test_trace_to_dict_fields(self):
        self.engine.evaluate(
            letter_id="dl_101", already_replayed=True,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_101", session_id="ses_test",
        )
        traces = self.engine.get_traces()
        t = traces[0]
        self.assertIn("letter_id", t)
        self.assertIn("decision", t)
        self.assertIn("dry_run", t)
        self.assertIn("original_error_code", t)
        self.assertIn("correlation_id", t)

    def test_trace_limit(self):
        for i in range(10):
            self.engine.evaluate(
                letter_id=f"dl_11{i}", already_replayed=True,
                failure_class="execution_error", error_code="E500",
                correlation_id=f"corr_11{i}",
            )
        traces = self.engine.get_traces(limit=5)
        self.assertEqual(len(traces), 5)


class TestEngineStats(unittest.TestCase):
    """Engine stats must reflect current state."""

    def test_initial_stats(self):
        engine = DLQReplayPolicyEngine()
        stats = engine.get_stats()
        self.assertEqual(stats["total_traces"], 0)
        self.assertEqual(stats["replays_in_window"], 0)
        self.assertEqual(stats["blocked_letters"], 0)

    def test_stats_after_operations(self):
        engine = DLQReplayPolicyEngine()
        engine.evaluate(
            letter_id="dl_120", already_replayed=False,
            failure_class="execution_error", error_code="E500",
            correlation_id="corr_120", dry_run=False,
        )
        engine.block_letter("dl_blocked")
        engine.record_lineage("corr_o", "act_o")
        stats = engine.get_stats()
        self.assertEqual(stats["total_traces"], 1)
        self.assertEqual(stats["replays_in_window"], 1)
        self.assertEqual(stats["blocked_letters"], 1)
        self.assertEqual(stats["tracked_lineages"], 1)


if __name__ == "__main__":
    unittest.main()
