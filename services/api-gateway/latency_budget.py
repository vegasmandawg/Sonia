"""
Latency Budget (v4.3 Epic C, v4.7 Epic C)

Per-stage p95/p99 tracking for promotion gate compliance.
Stages: asr, memory_read, model, tool, memory_write, tts, total

Stores last 10000 samples per stage in a circular buffer.
SLO checking returns a list of violations for promotion gates.

v4.7 additions:
  - SLOGuardrails: sustained breach detection, degrade/recover mode transitions
  - Recovery exit criteria: M consecutive_healthy windows required to exit_degrade
  - slo_status() diagnostics: current_mode, breach_history, time_in_degrade, clear_to_recover
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


# ============================================================================
# SLO Guardrails (v4.7 Epic C)
# ============================================================================

class SLOGuardrails:
    """
    Sustained breach detection with deterministic recovery exit criteria.

    Modes:
      NORMAL   - all SLO windows healthy
      DEGRADED - N consecutive breach windows exceeded threshold
      RECOVERING - breach cleared, waiting for M consecutive_healthy windows to exit_degrade

    Recovery requires recover_threshold (M) consecutive healthy windows.
    One-off spikes do not trigger degraded mode (requires sustained breach).
    """

    MODE_NORMAL = "normal"
    MODE_DEGRADED = "degraded"
    MODE_RECOVERING = "recovering"

    def __init__(
        self,
        breach_threshold: int = 3,
        recover_threshold: int = 5,
    ) -> None:
        """
        Args:
            breach_threshold: N consecutive breach windows to enter DEGRADED (sustained breach)
            recover_threshold: M consecutive_healthy windows to exit_degrade back to NORMAL
        """
        self._breach_threshold = breach_threshold
        self._recover_threshold = recover_threshold

        self._current_mode: str = self.MODE_NORMAL
        self._consecutive_breach: int = 0
        self._consecutive_healthy: int = 0
        self._breach_history: List[Dict[str, Any]] = []
        self._degrade_entered_at: Optional[float] = None
        self._degrade_reason: str = ""
        self._recovery_windows: int = 0
        self._lock = threading.Lock()

    @property
    def current_mode(self) -> str:
        return self._current_mode

    @property
    def slo_mode(self) -> str:
        """Alias for current_mode (gate compatibility)."""
        return self._current_mode

    @property
    def clear_to_recover(self) -> bool:
        """True when recovery exit criteria are met (M consecutive healthy windows)."""
        return self._consecutive_healthy >= self._recover_threshold

    def record_window(self, violations: List[Dict[str, Any]]) -> str:
        """
        Record an SLO evaluation window result.

        Args:
            violations: list of SLO violations from LatencyBudget.check_slo()

        Returns:
            Current mode after evaluation.
        """
        with self._lock:
            is_breach = len(violations) > 0
            now = time.time()

            if is_breach:
                self._consecutive_breach += 1
                self._consecutive_healthy = 0
                self._recovery_windows = 0

                self._breach_history.append({
                    "timestamp": now,
                    "violations": violations,
                    "consecutive": self._consecutive_breach,
                })
                # Bound history
                if len(self._breach_history) > 200:
                    self._breach_history = self._breach_history[-200:]

                # Sustained breach detection
                if self._current_mode == self.MODE_NORMAL and self._consecutive_breach >= self._breach_threshold:
                    self._current_mode = self.MODE_DEGRADED
                    self._degrade_entered_at = now
                    self._degrade_reason = f"sustained breach: {self._consecutive_breach} consecutive windows"
                elif self._current_mode == self.MODE_RECOVERING:
                    # Breach during recovery -> back to DEGRADED
                    self._current_mode = self.MODE_DEGRADED
                    self._degrade_reason = "breach during recovery"
            else:
                # Healthy window
                self._consecutive_breach = 0
                self._consecutive_healthy += 1
                self._recovery_windows += 1

                if self._current_mode == self.MODE_DEGRADED:
                    # Enter recovering mode
                    self._current_mode = self.MODE_RECOVERING
                    self._consecutive_healthy = 1

                if self._current_mode == self.MODE_RECOVERING:
                    # Check recovery exit criteria: M consecutive_healthy windows
                    if self._consecutive_healthy >= self._recover_threshold:
                        self._current_mode = self.MODE_NORMAL
                        self._degrade_entered_at = None
                        self._degrade_reason = ""

            return self._current_mode

    def slo_status(self) -> Dict[str, Any]:
        """
        Diagnostics snapshot for /v1/slo/status endpoint.

        Returns current_mode, breach_history, time_in_degrade, degrade_reason,
        clear_to_recover flag, and recovery window counters.
        """
        with self._lock:
            time_in_degrade = 0.0
            if self._degrade_entered_at is not None:
                time_in_degrade = round(time.time() - self._degrade_entered_at, 2)

            return {
                "current_mode": self._current_mode,
                "slo_mode": self._current_mode,
                "breach_history": self._breach_history[-20:],  # last 20 for endpoint
                "time_in_degrade": time_in_degrade,
                "degrade_reason": self._degrade_reason,
                "clear_to_recover": self._consecutive_healthy >= self._recover_threshold,
                "consecutive_breach": self._consecutive_breach,
                "consecutive_healthy": self._consecutive_healthy,
                "recovery_windows": self._recovery_windows,
                "breach_threshold": self._breach_threshold,
                "recover_threshold": self._recover_threshold,
            }

    def reset(self) -> None:
        """Reset to NORMAL mode (for testing or operator override)."""
        with self._lock:
            self._current_mode = self.MODE_NORMAL
            self._consecutive_breach = 0
            self._consecutive_healthy = 0
            self._degrade_entered_at = None
            self._degrade_reason = ""
            self._recovery_windows = 0


# Module-level singleton for SLO guardrails
_guardrails: Optional[SLOGuardrails] = None


def get_slo_guardrails(breach_threshold: int = 3, recover_threshold: int = 5) -> SLOGuardrails:
    """Get or create the singleton SLOGuardrails instance."""
    global _guardrails
    if _guardrails is None:
        _guardrails = SLOGuardrails(
            breach_threshold=breach_threshold,
            recover_threshold=recover_threshold,
        )
    return _guardrails
