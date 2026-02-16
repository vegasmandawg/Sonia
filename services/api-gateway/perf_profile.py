"""
Performance profile generator for sustained load evidence.

Provides:
- Sliding window p50/p95/p99 calculation
- SLO budget conformance checking
- Violation counting with threshold alerting
- Profile artifact generation
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SLOBudget:
    name: str
    metric: str  # e.g., "latency_ms", "error_rate"
    threshold: float
    percentile: Optional[int] = None  # e.g., 95 for p95

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "metric": self.metric,
            "threshold": self.threshold,
            "percentile": self.percentile,
        }


@dataclass
class SLOResult:
    budget: SLOBudget
    actual_value: float
    passed: bool
    margin: float  # positive = headroom, negative = violation

    def to_dict(self) -> dict:
        return {
            "name": self.budget.name,
            "metric": self.budget.metric,
            "threshold": self.budget.threshold,
            "actual": round(self.actual_value, 2),
            "passed": self.passed,
            "margin": round(self.margin, 2),
        }


@dataclass
class WindowStats:
    window_size: int
    count: int
    p50: float
    p95: float
    p99: float
    mean: float
    min_val: float
    max_val: float

    def to_dict(self) -> dict:
        return {
            "window_size": self.window_size,
            "count": self.count,
            "p50": round(self.p50, 2),
            "p95": round(self.p95, 2),
            "p99": round(self.p99, 2),
            "mean": round(self.mean, 2),
            "min": round(self.min_val, 2),
            "max": round(self.max_val, 2),
        }


@dataclass
class PerfProfile:
    total_samples: int
    windows: List[WindowStats] = field(default_factory=list)
    slo_results: List[SLOResult] = field(default_factory=list)
    violations: int = 0
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "total_samples": self.total_samples,
            "windows": [w.to_dict() for w in self.windows],
            "slo_results": [s.to_dict() for s in self.slo_results],
            "violations": self.violations,
            "passed": self.passed,
        }


def percentile(data: List[float], pct: int) -> float:
    """Calculate the pct-th percentile of a list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * pct / 100.0
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    d0 = sorted_data[f] * (c - k)
    d1 = sorted_data[c] * (k - f)
    return d0 + d1


class PerfProfiler:
    """Generates performance profiles from latency samples."""

    def __init__(
        self,
        window_size: int = 100,
        slo_budgets: Optional[List[SLOBudget]] = None,
    ):
        self.window_size = window_size
        self.slo_budgets = slo_budgets or []
        self._samples: List[float] = []

    def add_sample(self, value: float) -> None:
        """Add a latency/metric sample."""
        self._samples.append(value)

    def add_samples(self, values: List[float]) -> None:
        """Add multiple samples."""
        self._samples.extend(values)

    def compute_window_stats(self, data: List[float], window_size: int) -> WindowStats:
        """Compute stats for a window of data."""
        if not data:
            return WindowStats(
                window_size=window_size, count=0,
                p50=0, p95=0, p99=0, mean=0, min_val=0, max_val=0,
            )
        return WindowStats(
            window_size=window_size,
            count=len(data),
            p50=percentile(data, 50),
            p95=percentile(data, 95),
            p99=percentile(data, 99),
            mean=statistics.mean(data),
            min_val=min(data),
            max_val=max(data),
        )

    def generate_profile(self) -> PerfProfile:
        """Generate full performance profile with sliding windows."""
        if not self._samples:
            return PerfProfile(total_samples=0, passed=True)

        windows: List[WindowStats] = []
        # Overall stats
        windows.append(self.compute_window_stats(self._samples, len(self._samples)))

        # Sliding windows
        if len(self._samples) > self.window_size:
            for i in range(0, len(self._samples) - self.window_size + 1, self.window_size):
                chunk = self._samples[i:i + self.window_size]
                windows.append(self.compute_window_stats(chunk, self.window_size))

        # Check SLO budgets
        slo_results: List[SLOResult] = []
        violations = 0
        overall = windows[0]  # overall stats

        for budget in self.slo_budgets:
            if budget.percentile == 50:
                actual = overall.p50
            elif budget.percentile == 95:
                actual = overall.p95
            elif budget.percentile == 99:
                actual = overall.p99
            else:
                actual = overall.mean

            margin = budget.threshold - actual
            passed = actual <= budget.threshold
            if not passed:
                violations += 1

            slo_results.append(SLOResult(
                budget=budget,
                actual_value=actual,
                passed=passed,
                margin=margin,
            ))

        return PerfProfile(
            total_samples=len(self._samples),
            windows=windows,
            slo_results=slo_results,
            violations=violations,
            passed=violations == 0,
        )

    def check_slo(self, budget: SLOBudget) -> SLOResult:
        """Check a single SLO budget against current samples."""
        overall = self.compute_window_stats(self._samples, len(self._samples))
        if budget.percentile == 50:
            actual = overall.p50
        elif budget.percentile == 95:
            actual = overall.p95
        elif budget.percentile == 99:
            actual = overall.p99
        else:
            actual = overall.mean

        margin = budget.threshold - actual
        return SLOResult(
            budget=budget,
            actual_value=actual,
            passed=actual <= budget.threshold,
            margin=margin,
        )

    def get_summary(self) -> dict:
        """Return profiler summary."""
        profile = self.generate_profile()
        return {
            "total_samples": profile.total_samples,
            "violations": profile.violations,
            "passed": profile.passed,
            "windows": len(profile.windows),
        }

    def clear(self) -> None:
        """Clear all samples."""
        self._samples.clear()
