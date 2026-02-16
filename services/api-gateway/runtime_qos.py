"""
v3.7 M3 — Runtime QoS Engine

Centralised SLO monitoring, latency tracking, and adaptive throttling.
Deterministic per-turn quality annotations and SLO compliance audit.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.runtime_qos")


class SLOTier(str, Enum):
    """SLO tiers for different operation types."""
    INTERACTIVE = "interactive"     # p95 < 500ms
    STANDARD = "standard"          # p95 < 2000ms
    BATCH = "batch"                # p95 < 10000ms
    BACKGROUND = "background"      # no hard SLO


class QoSViolationType(str, Enum):
    """Types of QoS violations."""
    LATENCY_EXCEEDED = "latency_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    RATE_LIMIT_HIT = "rate_limit_hit"
    ERROR_RATE_HIGH = "error_rate_high"
    TIMEOUT = "timeout"


@dataclass
class SLOTarget:
    """SLO target for a specific tier."""
    tier: SLOTier
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_rate_pct: float = 1.0  # max acceptable error rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "error_rate_pct": self.error_rate_pct,
        }


# ── Default SLO Targets ─────────────────────────────────────────────────────

DEFAULT_SLO_TARGETS: Dict[str, SLOTarget] = {
    SLOTier.INTERACTIVE.value: SLOTarget(
        tier=SLOTier.INTERACTIVE, p50_ms=100, p95_ms=500, p99_ms=1000,
    ),
    SLOTier.STANDARD.value: SLOTarget(
        tier=SLOTier.STANDARD, p50_ms=500, p95_ms=2000, p99_ms=5000,
    ),
    SLOTier.BATCH.value: SLOTarget(
        tier=SLOTier.BATCH, p50_ms=2000, p95_ms=10000, p99_ms=30000,
    ),
    SLOTier.BACKGROUND.value: SLOTarget(
        tier=SLOTier.BACKGROUND, p50_ms=5000, p95_ms=30000, p99_ms=60000,
    ),
}


@dataclass
class LatencyRecord:
    """Single latency measurement with context."""
    operation: str
    tier: str
    duration_ms: float
    timestamp: float = field(default_factory=time.monotonic)
    violated_slo: bool = False
    violation_type: str = ""
    correlation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "operation": self.operation,
            "tier": self.tier,
            "duration_ms": self.duration_ms,
            "violated_slo": self.violated_slo,
        }
        if self.correlation_id:
            d["correlation_id"] = self.correlation_id
        if self.violation_type:
            d["violation_type"] = self.violation_type
        return d


@dataclass
class QoSViolation:
    """A recorded QoS violation for audit."""
    violation_type: str
    operation: str
    tier: str
    observed_value: float
    threshold: float
    timestamp: float = field(default_factory=time.monotonic)
    correlation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_type": self.violation_type,
            "operation": self.operation,
            "tier": self.tier,
            "observed_value": self.observed_value,
            "threshold": self.threshold,
            "correlation_id": self.correlation_id,
        }


@dataclass
class TurnQoSAnnotation:
    """Quality annotation attached to a turn result."""
    turn_id: str
    tier: str
    total_ms: float
    slo_met: bool
    latency_breakdown: Dict[str, float] = field(default_factory=dict)
    violations: List[str] = field(default_factory=list)
    budget_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "tier": self.tier,
            "total_ms": self.total_ms,
            "slo_met": self.slo_met,
            "latency_breakdown": self.latency_breakdown,
            "violations": self.violations,
            "budget_results": self.budget_results,
        }


class RuntimeQoSEngine:
    """
    Centralised SLO monitoring and QoS enforcement.

    Key invariants:
    1. Every operation is measured and compared against its SLO tier.
    2. Violations are recorded with full traceability.
    3. Latency history is bounded (sliding window).
    4. Turn annotations are deterministic (same inputs -> same output).
    """

    def __init__(
        self,
        slo_targets: Optional[Dict[str, SLOTarget]] = None,
        history_window_seconds: float = 300.0,
        max_history: int = 2000,
    ):
        self._slo_targets = slo_targets or dict(DEFAULT_SLO_TARGETS)
        self._window_s = history_window_seconds
        self._max_history = max_history
        self._latency_history: List[LatencyRecord] = []
        self._violations: List[QoSViolation] = []
        self._max_violations: int = 1000
        self._total_operations: int = 0
        self._total_violations: int = 0

    def get_slo_target(self, tier: str) -> Optional[SLOTarget]:
        """Get SLO target for a tier."""
        return self._slo_targets.get(tier)

    def record_latency(
        self,
        operation: str,
        duration_ms: float,
        tier: str = SLOTier.STANDARD.value,
        correlation_id: str = "",
    ) -> LatencyRecord:
        """
        Record a latency measurement and check against SLO.

        Returns the LatencyRecord with violation info if applicable.
        """
        self._total_operations += 1
        target = self._slo_targets.get(tier)

        violated = False
        violation_type = ""
        if target and duration_ms > target.p95_ms:
            violated = True
            violation_type = QoSViolationType.LATENCY_EXCEEDED.value
            self._record_violation(QoSViolation(
                violation_type=violation_type,
                operation=operation,
                tier=tier,
                observed_value=duration_ms,
                threshold=target.p95_ms,
                correlation_id=correlation_id,
            ))

        record = LatencyRecord(
            operation=operation,
            tier=tier,
            duration_ms=duration_ms,
            violated_slo=violated,
            violation_type=violation_type,
            correlation_id=correlation_id,
        )
        self._latency_history.append(record)

        # Bound history
        if len(self._latency_history) > self._max_history:
            self._latency_history = self._latency_history[-self._max_history:]

        return record

    def record_timeout(
        self,
        operation: str,
        timeout_ms: float,
        tier: str = SLOTier.STANDARD.value,
        correlation_id: str = "",
    ) -> QoSViolation:
        """Record a timeout violation."""
        violation = QoSViolation(
            violation_type=QoSViolationType.TIMEOUT.value,
            operation=operation,
            tier=tier,
            observed_value=timeout_ms,
            threshold=timeout_ms,
            correlation_id=correlation_id,
        )
        self._record_violation(violation)

        # Also record as latency
        self.record_latency(operation, timeout_ms, tier, correlation_id)

        return violation

    def annotate_turn(
        self,
        turn_id: str,
        tier: str,
        total_ms: float,
        latency_breakdown: Optional[Dict[str, float]] = None,
        budget_results: Optional[List[Dict[str, Any]]] = None,
    ) -> TurnQoSAnnotation:
        """
        Generate a deterministic QoS annotation for a turn.

        Returns TurnQoSAnnotation with SLO compliance status.
        """
        target = self._slo_targets.get(tier)
        slo_met = True
        violations = []

        if target:
            if total_ms > target.p95_ms:
                slo_met = False
                violations.append(f"total_ms {total_ms:.1f} > p95 {target.p95_ms}")

        # Check individual breakdown components
        if latency_breakdown:
            for component, ms in latency_breakdown.items():
                if ms > 0 and target and ms > target.p95_ms * 0.8:
                    violations.append(f"{component} {ms:.1f}ms near SLO ceiling")

        return TurnQoSAnnotation(
            turn_id=turn_id,
            tier=tier,
            total_ms=total_ms,
            slo_met=slo_met,
            latency_breakdown=latency_breakdown or {},
            violations=violations,
            budget_results=budget_results or [],
        )

    def get_percentiles(
        self,
        operation: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> Dict[str, float]:
        """
        Calculate p50/p95/p99 from recent latency history.

        Optionally filter by operation and/or tier.
        """
        now = time.monotonic()
        cutoff = now - self._window_s

        records = [
            r for r in self._latency_history
            if r.timestamp > cutoff
        ]

        if operation:
            records = [r for r in records if r.operation == operation]
        if tier:
            records = [r for r in records if r.tier == tier]

        if not records:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}

        durations = sorted(r.duration_ms for r in records)
        n = len(durations)

        return {
            "p50": durations[int(n * 0.5)] if n > 0 else 0.0,
            "p95": durations[min(int(n * 0.95), n - 1)] if n > 0 else 0.0,
            "p99": durations[min(int(n * 0.99), n - 1)] if n > 0 else 0.0,
            "count": n,
        }

    def _record_violation(self, violation: QoSViolation) -> None:
        """Record a QoS violation."""
        self._total_violations += 1
        self._violations.append(violation)
        if len(self._violations) > self._max_violations:
            self._violations = self._violations[-self._max_violations:]

    def get_violations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent QoS violations."""
        return [v.to_dict() for v in self._violations[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """Return QoS engine statistics."""
        return {
            "total_operations": self._total_operations,
            "total_violations": self._total_violations,
            "history_size": len(self._latency_history),
            "slo_tiers": list(self._slo_targets.keys()),
            "tier_count": len(self._slo_targets),
        }

    def get_slo_table(self) -> List[Dict[str, Any]]:
        """Export all SLO targets for operator review."""
        return [t.to_dict() for t in self._slo_targets.values()]
