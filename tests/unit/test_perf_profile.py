"""
Unit tests for perf_profile.py — PerfProfiler.

Covers:
- Sample collection
- Window statistics (p50, p95, p99)
- SLO budget checking
- Violation detection
- Profile generation
- Edge cases (empty, single sample)
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"S:\services\api-gateway")

from perf_profile import (
    PerfProfiler,
    SLOBudget,
    SLOResult,
    WindowStats,
    PerfProfile,
    percentile,
)


class TestPerfProfiler:
    """Tests for PerfProfiler."""

    def test_add_sample(self):
        p = PerfProfiler()
        p.add_sample(100.0)
        p.add_sample(200.0)
        assert len(p._samples) == 2

    def test_add_samples_bulk(self):
        p = PerfProfiler()
        p.add_samples([10, 20, 30, 40, 50])
        assert len(p._samples) == 5

    def test_percentile_function(self):
        data = list(range(1, 101))  # 1..100
        assert percentile(data, 50) == 50.5
        assert percentile(data, 95) >= 95
        assert percentile(data, 99) >= 99

    def test_percentile_empty(self):
        assert percentile([], 50) == 0.0

    def test_percentile_single(self):
        assert percentile([42.0], 50) == 42.0
        assert percentile([42.0], 99) == 42.0

    def test_window_stats_computation(self):
        p = PerfProfiler()
        data = [10, 20, 30, 40, 50]
        stats = p.compute_window_stats(data, 5)
        assert stats.count == 5
        assert stats.min_val == 10
        assert stats.max_val == 50
        assert stats.mean == 30
        assert stats.p50 > 0

    def test_window_stats_empty(self):
        p = PerfProfiler()
        stats = p.compute_window_stats([], 0)
        assert stats.count == 0
        assert stats.p50 == 0

    def test_generate_profile_basic(self):
        p = PerfProfiler(window_size=5)
        p.add_samples([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        profile = p.generate_profile()
        assert profile.total_samples == 10
        assert len(profile.windows) > 1  # overall + sliding

    def test_generate_profile_empty(self):
        p = PerfProfiler()
        profile = p.generate_profile()
        assert profile.total_samples == 0
        assert profile.passed is True

    def test_slo_budget_pass(self):
        p = PerfProfiler()
        p.add_samples([10, 20, 30, 40, 50])
        budget = SLOBudget(name="latency_p95", metric="latency_ms", threshold=200, percentile=95)
        result = p.check_slo(budget)
        assert result.passed is True
        assert result.margin > 0

    def test_slo_budget_fail(self):
        p = PerfProfiler()
        p.add_samples([100, 200, 300, 400, 500])
        budget = SLOBudget(name="latency_p95", metric="latency_ms", threshold=100, percentile=95)
        result = p.check_slo(budget)
        assert result.passed is False
        assert result.margin < 0

    def test_profile_with_slo_budgets(self):
        budgets = [
            SLOBudget(name="p95_lat", metric="latency_ms", threshold=200, percentile=95),
            SLOBudget(name="p99_lat", metric="latency_ms", threshold=500, percentile=99),
        ]
        p = PerfProfiler(slo_budgets=budgets)
        p.add_samples([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        profile = p.generate_profile()
        assert len(profile.slo_results) == 2
        assert profile.violations == 0
        assert profile.passed is True

    def test_profile_with_violation(self):
        budgets = [
            SLOBudget(name="strict", metric="latency_ms", threshold=10, percentile=95),
        ]
        p = PerfProfiler(slo_budgets=budgets)
        p.add_samples([100, 200, 300])
        profile = p.generate_profile()
        assert profile.violations == 1
        assert profile.passed is False

    def test_window_stats_to_dict(self):
        p = PerfProfiler()
        stats = p.compute_window_stats([10, 20, 30], 3)
        d = stats.to_dict()
        assert "p50" in d
        assert "p95" in d
        assert "mean" in d

    def test_slo_result_to_dict(self):
        budget = SLOBudget(name="test", metric="m", threshold=100, percentile=95)
        result = SLOResult(budget=budget, actual_value=50, passed=True, margin=50)
        d = result.to_dict()
        assert d["passed"] is True
        assert d["margin"] == 50

    def test_profile_to_dict(self):
        p = PerfProfiler()
        p.add_samples([10, 20, 30])
        profile = p.generate_profile()
        d = profile.to_dict()
        assert "total_samples" in d
        assert "windows" in d
        assert "passed" in d

    def test_get_summary(self):
        p = PerfProfiler()
        p.add_samples([10, 20, 30])
        summary = p.get_summary()
        assert summary["total_samples"] == 3

    def test_clear(self):
        p = PerfProfiler()
        p.add_samples([1, 2, 3])
        p.clear()
        assert len(p._samples) == 0

    def test_slo_budget_to_dict(self):
        budget = SLOBudget(name="test", metric="latency_ms", threshold=200, percentile=95)
        d = budget.to_dict()
        assert d["name"] == "test"
        assert d["threshold"] == 200
