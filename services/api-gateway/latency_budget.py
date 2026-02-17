"""
Latency Budget (v4.3 Epic C)

Per-stage p95/p99 tracking for promotion gate compliance.
Stages: asr, memory_read, model, tool, memory_write, tts, total

Stores last 10000 samples per stage in a circular buffer.
SLO checking returns a list of violations for promotion gates.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional


# Default number of samples retained per stage
_DEFAULT_BUFFER_SIZE = 10000


class _CircularBuffer:
    """Fixed-size circular buffer for float samples."""

    __slots__ = ("_buf", "_size", "_pos", "_count")

    def __init__(self, size: int = _DEFAULT_BUFFER_SIZE) -> None:
        self._size = size
        self._buf: List[float] = [0.0] * size
        self._pos = 0
        self._count = 0

    def append(self, value: float) -> None:
        self._buf[self._pos] = value
        self._pos = (self._pos + 1) % self._size
        if self._count < self._size:
            self._count += 1

    def samples(self) -> List[float]:
        """Return all stored samples in insertion order."""
        if self._count < self._size:
            return self._buf[: self._count]
        # Wrap-around: oldest is at _pos, newest at _pos-1
        return self._buf[self._pos :] + self._buf[: self._pos]

    @property
    def count(self) -> int:
        return self._count


class LatencyBudget:
    """
    Per-stage latency tracking with percentile computation and SLO checking.

    Usage:
        budget = LatencyBudget()
        budget.record("model", 1234.5, "sess_abc")
        budget.record("memory_read", 45.2, "sess_abc")
        print(budget.percentile("model", 0.95))
        print(budget.summary())
        violations = budget.check_slo({"model": {"p95": 5000}})
    """

    def __init__(self, buffer_size: int = _DEFAULT_BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size
        self._stages: Dict[str, _CircularBuffer] = {}
        self._session_counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def _ensure_stage(self, stage: str) -> _CircularBuffer:
        if stage not in self._stages:
            self._stages[stage] = _CircularBuffer(self._buffer_size)
        return self._stages[stage]

    def record(self, stage: str, duration_ms: float, session_id: str = "") -> None:
        """Record a latency sample for a given stage."""
        with self._lock:
            buf = self._ensure_stage(stage)
            buf.append(duration_ms)
            if session_id:
                self._session_counts[session_id] += 1

    def percentile(self, stage: str, p: float) -> float:
        """
        Compute the p-th percentile for a stage.

        p should be between 0.0 and 1.0 (e.g. 0.95 for p95).
        Returns 0.0 if no samples exist.
        """
        if p < 0.0 or p > 1.0:
            raise ValueError(f"percentile p must be in [0, 1], got {p}")

        with self._lock:
            buf = self._stages.get(stage)
            if buf is None or buf.count == 0:
                return 0.0
            data = sorted(buf.samples())

        n = len(data)
        if n == 1:
            return data[0]

        # Linear interpolation percentile (like numpy default)
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return round(data[lo] + (data[hi] - data[lo]) * frac, 2)

    def summary(self) -> Dict[str, Dict[str, float]]:
        """
        Return per-stage summary with p50, p95, p99, count.
        """
        with self._lock:
            stages = list(self._stages.keys())

        result: Dict[str, Dict[str, float]] = {}
        for stage in stages:
            result[stage] = {
                "p50": self.percentile(stage, 0.50),
                "p95": self.percentile(stage, 0.95),
                "p99": self.percentile(stage, 0.99),
                "count": self._stages[stage].count if stage in self._stages else 0,
            }
        return result

    def check_slo(self, slo_config: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
        """
        Check latency against SLO targets.

        slo_config format:
            {
                "asr": {"p95": 500},
                "model": {"p95": 5000},
                "total": {"p95": 8000, "p99": 12000},
            }

        Returns a list of violation dicts:
            [{"stage": "model", "metric": "p95", "threshold": 5000, "actual": 5234.1}]
        """
        violations: List[Dict[str, Any]] = []

        for stage, thresholds in slo_config.items():
            for metric, threshold in thresholds.items():
                # Parse metric name -> percentile value
                if metric.startswith("p"):
                    try:
                        p_val = int(metric[1:]) / 100.0
                    except ValueError:
                        continue
                else:
                    continue

                actual = self.percentile(stage, p_val)
                if actual > threshold and actual > 0.0:
                    violations.append({
                        "stage": stage,
                        "metric": metric,
                        "threshold": threshold,
                        "actual": actual,
                    })

        return violations
