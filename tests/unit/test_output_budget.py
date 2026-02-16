"""v3.7 M3 — Output Budget Enforcement Tests.

Validates:
- Default budget configuration (5 dimensions)
- Text truncation (hard cut, sentence boundary, reject)
- Count enforcement (drop oldest, reject, hard cut)
- Warning threshold detection
- Dry enforcement (within budget) produces no truncation
- Enforcement log bounded
- Stats accuracy
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join("S:", os.sep, "services", "api-gateway"))

from output_budget import (
    BudgetDimension,
    TruncationStrategy,
    BudgetLimit,
    BudgetResult,
    OutputBudgetEnforcer,
    DEFAULT_BUDGETS,
)


class TestDefaultBudgets(unittest.TestCase):
    """Default budget configuration must cover all 5 dimensions."""

    def test_five_dimensions(self):
        self.assertEqual(len(DEFAULT_BUDGETS), 5)

    def test_output_chars_budget(self):
        b = DEFAULT_BUDGETS[BudgetDimension.OUTPUT_CHARS.value]
        self.assertEqual(b.max_value, 4000)
        self.assertEqual(b.strategy, TruncationStrategy.SENTENCE_BOUNDARY)

    def test_context_chars_budget(self):
        b = DEFAULT_BUDGETS[BudgetDimension.CONTEXT_CHARS.value]
        self.assertEqual(b.max_value, 7000)

    def test_tool_calls_budget(self):
        b = DEFAULT_BUDGETS[BudgetDimension.TOOL_CALLS.value]
        self.assertEqual(b.max_value, 5)
        self.assertEqual(b.strategy, TruncationStrategy.REJECT)

    def test_vision_frames_budget(self):
        b = DEFAULT_BUDGETS[BudgetDimension.VISION_FRAMES.value]
        self.assertEqual(b.max_value, 3)
        self.assertEqual(b.strategy, TruncationStrategy.DROP_OLDEST)

    def test_all_dimensions_enum_valid(self):
        for dim in BudgetDimension:
            self.assertIn(dim.value, DEFAULT_BUDGETS)


class TestTextEnforcement(unittest.TestCase):
    """Text enforcement must truncate deterministically."""

    def setUp(self):
        self.enforcer = OutputBudgetEnforcer()

    def test_short_text_passes(self):
        text, result = self.enforcer.enforce_text("Hello world")
        self.assertEqual(text, "Hello world")
        self.assertFalse(result.truncated)

    def test_long_text_truncated(self):
        long_text = "A" * 5000
        text, result = self.enforcer.enforce_text(long_text)
        self.assertLessEqual(len(text), 4000)
        self.assertTrue(result.truncated)
        self.assertEqual(result.original_size, 5000)

    def test_sentence_boundary_truncation(self):
        # Build text with clear sentence boundaries
        sentences = "Short sentence. " * 300  # ~4800 chars
        text, result = self.enforcer.enforce_text(sentences)
        if result.truncated:
            self.assertTrue(text.endswith("."))

    def test_hard_cut_strategy(self):
        enforcer = OutputBudgetEnforcer(budgets={
            "test": BudgetLimit(
                dimension=BudgetDimension.OUTPUT_CHARS,
                max_value=10,
                strategy=TruncationStrategy.HARD_CUT,
            ),
        })
        text, result = enforcer.enforce_text("12345678901234567890", dimension="test")
        self.assertEqual(len(text), 10)
        self.assertEqual(text, "1234567890")

    def test_reject_strategy(self):
        enforcer = OutputBudgetEnforcer(budgets={
            "test": BudgetLimit(
                dimension=BudgetDimension.OUTPUT_CHARS,
                max_value=5,
                strategy=TruncationStrategy.REJECT,
            ),
        })
        text, result = enforcer.enforce_text("Too long text", dimension="test")
        self.assertEqual(text, "")
        self.assertTrue(result.truncated)

    def test_unknown_dimension_passthrough(self):
        text, result = self.enforcer.enforce_text("anything", dimension="unknown")
        self.assertEqual(text, "anything")
        self.assertFalse(result.truncated)


class TestCountEnforcement(unittest.TestCase):
    """Count enforcement must limit lists deterministically."""

    def setUp(self):
        self.enforcer = OutputBudgetEnforcer()

    def test_small_list_passes(self):
        items = [1, 2]
        result_items, result = self.enforcer.enforce_count(
            items, BudgetDimension.VISION_FRAMES.value)
        self.assertEqual(len(result_items), 2)
        self.assertFalse(result.truncated)

    def test_over_limit_drop_oldest(self):
        items = [1, 2, 3, 4, 5]
        result_items, result = self.enforcer.enforce_count(
            items, BudgetDimension.VISION_FRAMES.value)
        self.assertEqual(len(result_items), 3)
        self.assertEqual(result_items, [3, 4, 5])  # oldest dropped
        self.assertTrue(result.truncated)

    def test_reject_strategy_count(self):
        items = list(range(10))
        result_items, result = self.enforcer.enforce_count(
            items, BudgetDimension.TOOL_CALLS.value)
        self.assertEqual(len(result_items), 0)
        self.assertTrue(result.truncated)

    def test_exact_limit_passes(self):
        items = [1, 2, 3]
        result_items, result = self.enforcer.enforce_count(
            items, BudgetDimension.VISION_FRAMES.value)
        self.assertEqual(len(result_items), 3)
        self.assertFalse(result.truncated)


class TestWarningThreshold(unittest.TestCase):
    """Warning should trigger when usage approaches limit."""

    def test_warn_at_80pct(self):
        enforcer = OutputBudgetEnforcer(budgets={
            "test": BudgetLimit(
                dimension=BudgetDimension.OUTPUT_CHARS,
                max_value=100,
                strategy=TruncationStrategy.HARD_CUT,
                warn_at_pct=0.8,
            ),
        })
        # 85 chars should trigger warning
        _, result = enforcer.enforce_text("A" * 85, dimension="test")
        self.assertTrue(result.warn)
        self.assertFalse(result.truncated)

    def test_no_warn_below_threshold(self):
        enforcer = OutputBudgetEnforcer(budgets={
            "test": BudgetLimit(
                dimension=BudgetDimension.OUTPUT_CHARS,
                max_value=100,
                strategy=TruncationStrategy.HARD_CUT,
                warn_at_pct=0.8,
            ),
        })
        _, result = enforcer.enforce_text("A" * 50, dimension="test")
        self.assertFalse(result.warn)


class TestBudgetResultAudit(unittest.TestCase):
    """Budget results must support audit trail."""

    def test_result_to_dict(self):
        result = BudgetResult(
            dimension="output_chars",
            original_size=5000,
            enforced_size=4000,
            truncated=True,
            strategy_used="sentence_boundary",
            budget_remaining=0,
            warn=True,
        )
        d = result.to_dict()
        self.assertEqual(d["dimension"], "output_chars")
        self.assertEqual(d["original_size"], 5000)
        self.assertTrue(d["truncated"])

    def test_enforcement_log_recorded(self):
        enforcer = OutputBudgetEnforcer()
        enforcer.enforce_text("test")
        log = enforcer.get_enforcement_log()
        self.assertEqual(len(log), 1)

    def test_enforcement_log_bounded(self):
        enforcer = OutputBudgetEnforcer()
        for i in range(20):
            enforcer.enforce_text(f"text_{i}")
        log = enforcer.get_enforcement_log(limit=5)
        self.assertEqual(len(log), 5)


class TestEnforcerStats(unittest.TestCase):
    """Enforcer stats must reflect current state."""

    def test_initial_stats(self):
        enforcer = OutputBudgetEnforcer()
        stats = enforcer.get_stats()
        self.assertEqual(stats["total_enforcements"], 0)
        self.assertEqual(stats["total_truncations"], 0)
        self.assertEqual(stats["dimension_count"], 5)

    def test_stats_after_operations(self):
        enforcer = OutputBudgetEnforcer()
        enforcer.enforce_text("short")
        enforcer.enforce_text("A" * 5000)
        stats = enforcer.get_stats()
        self.assertEqual(stats["total_enforcements"], 2)
        self.assertEqual(stats["total_truncations"], 1)

    def test_budget_table_exposed(self):
        enforcer = OutputBudgetEnforcer()
        table = enforcer.get_budget_table()
        self.assertEqual(len(table), 5)
        self.assertIn("dimension", table[0])
        self.assertIn("max_value", table[0])

    def test_set_limit(self):
        enforcer = OutputBudgetEnforcer()
        enforcer.set_limit("custom", BudgetLimit(
            dimension=BudgetDimension.OUTPUT_CHARS,
            max_value=100,
        ))
        self.assertIsNotNone(enforcer.get_limit("custom"))


if __name__ == "__main__":
    unittest.main()
