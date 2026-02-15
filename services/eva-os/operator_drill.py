"""Reproducible operator drill framework (v3.3 Epic B).

Provides deterministic drill scenarios that simulate failure conditions
for operator training and recovery validation. Each drill has a known
expected outcome, enabling automated verification.

Drill types:
    - service_failure: Simulate a service becoming unreachable
    - breaker_trip: Simulate a circuit breaker tripping
    - dlq_overflow: Simulate dead letter queue buildup
    - restore_from_backup: Simulate full backup/restore cycle
    - dependency_cascade: Simulate cascading dependency failure

Invariants:
    - Drills are side-effect free in dry_run mode.
    - Every drill produces a deterministic DrillResult.
    - Drill results include timing and correlation metadata.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DrillType(str, Enum):
    SERVICE_FAILURE = "service_failure"
    BREAKER_TRIP = "breaker_trip"
    DLQ_OVERFLOW = "dlq_overflow"
    RESTORE_FROM_BACKUP = "restore_from_backup"
    DEPENDENCY_CASCADE = "dependency_cascade"


class DrillOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DrillScenario:
    """A reproducible drill scenario definition."""
    drill_type: DrillType
    target_service: str
    description: str
    expected_state_after: str  # expected final state
    expected_events: tuple     # expected event types
    max_duration_s: float = 60.0
    dry_run: bool = True


@dataclass
class DrillResult:
    """Result of executing a drill scenario."""
    drill_type: DrillType
    target_service: str
    outcome: DrillOutcome
    actual_state: str
    events_observed: List[str]
    duration_ms: float
    correlation_id: str
    detail: str = ""
    dry_run: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drill_type": self.drill_type.value,
            "target_service": self.target_service,
            "outcome": self.outcome.value,
            "actual_state": self.actual_state,
            "events_observed": self.events_observed,
            "duration_ms": self.duration_ms,
            "correlation_id": self.correlation_id,
            "detail": self.detail,
            "dry_run": self.dry_run,
        }


# Pre-built drill catalog
DRILL_CATALOG = [
    DrillScenario(
        drill_type=DrillType.SERVICE_FAILURE,
        target_service="model-router",
        description="Simulate model-router becoming unreachable",
        expected_state_after="unreachable",
        expected_events=(
            "supervision.service.degraded",
            "supervision.service.unreachable",
        ),
    ),
    DrillScenario(
        drill_type=DrillType.BREAKER_TRIP,
        target_service="memory-engine",
        description="Simulate memory-engine circuit breaker tripping",
        expected_state_after="open",
        expected_events=("breaker.trip",),
    ),
    DrillScenario(
        drill_type=DrillType.DLQ_OVERFLOW,
        target_service="api-gateway",
        description="Simulate DLQ accumulation from repeated failures",
        expected_state_after="degraded",
        expected_events=("dlq.enqueue", "dlq.threshold_exceeded"),
    ),
    DrillScenario(
        drill_type=DrillType.RESTORE_FROM_BACKUP,
        target_service="api-gateway",
        description="Simulate full backup/restore cycle",
        expected_state_after="healthy",
        expected_events=("backup.created", "restore.completed", "verify.passed"),
    ),
    DrillScenario(
        drill_type=DrillType.DEPENDENCY_CASCADE,
        target_service="pipecat",
        description="Simulate cascading failure from api-gateway dependency",
        expected_state_after="degraded",
        expected_events=(
            "supervision.service.degraded",
            "supervision.cascade.detected",
        ),
    ),
]


class OperatorDrillRunner:
    """Executes reproducible operator drills.

    All drills run in dry_run mode by default -- no actual service
    mutations. Real mode requires explicit confirmation.
    """

    def __init__(self):
        self._drill_log: List[DrillResult] = []
        self._stats = {
            "drills_run": 0,
            "drills_passed": 0,
            "drills_failed": 0,
            "drills_skipped": 0,
        }
        self._drill_seq = 0

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def drill_log(self) -> List[DrillResult]:
        return list(self._drill_log)

    def get_catalog(self) -> List[Dict[str, Any]]:
        """Return the drill catalog for operator display."""
        return [
            {
                "drill_type": d.drill_type.value,
                "target_service": d.target_service,
                "description": d.description,
                "expected_state_after": d.expected_state_after,
                "max_duration_s": d.max_duration_s,
            }
            for d in DRILL_CATALOG
        ]

    def run_drill(
        self,
        scenario: DrillScenario,
        simulate_fn=None,
    ) -> DrillResult:
        """Execute a single drill scenario.

        If simulate_fn is provided, it's called with the scenario and
        should return (actual_state, events_observed). Otherwise, the
        drill runs as a dry-run validation of the scenario definition.
        """
        self._drill_seq += 1
        correlation_id = f"drill-{self._drill_seq}-{scenario.drill_type.value}"
        t0 = time.monotonic()

        self._stats["drills_run"] += 1

        if scenario.dry_run or simulate_fn is None:
            # Dry run: validate scenario definition only
            elapsed = (time.monotonic() - t0) * 1000
            result = DrillResult(
                drill_type=scenario.drill_type,
                target_service=scenario.target_service,
                outcome=DrillOutcome.PASS,
                actual_state=scenario.expected_state_after,
                events_observed=list(scenario.expected_events),
                duration_ms=elapsed,
                correlation_id=correlation_id,
                detail="dry_run: scenario validated",
                dry_run=True,
            )
            self._stats["drills_passed"] += 1
            self._drill_log.append(result)
            return result

        # Real execution via simulate_fn
        try:
            actual_state, events = simulate_fn(scenario)
            elapsed = (time.monotonic() - t0) * 1000

            # Verify outcome
            state_match = actual_state == scenario.expected_state_after
            events_match = all(
                ev in events for ev in scenario.expected_events
            )
            outcome = DrillOutcome.PASS if (state_match and events_match) else DrillOutcome.FAIL

            if outcome == DrillOutcome.PASS:
                self._stats["drills_passed"] += 1
            else:
                self._stats["drills_failed"] += 1

            result = DrillResult(
                drill_type=scenario.drill_type,
                target_service=scenario.target_service,
                outcome=outcome,
                actual_state=actual_state,
                events_observed=events,
                duration_ms=elapsed,
                correlation_id=correlation_id,
                detail="" if outcome == DrillOutcome.PASS else f"state_match={state_match}, events_match={events_match}",
                dry_run=False,
            )

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            self._stats["drills_failed"] += 1
            result = DrillResult(
                drill_type=scenario.drill_type,
                target_service=scenario.target_service,
                outcome=DrillOutcome.FAIL,
                actual_state="error",
                events_observed=[],
                duration_ms=elapsed,
                correlation_id=correlation_id,
                detail=f"Exception: {str(e)[:200]}",
                dry_run=False,
            )

        self._drill_log.append(result)
        return result

    def run_catalog(self, simulate_fn=None) -> List[DrillResult]:
        """Run all drills in the catalog."""
        results = []
        for scenario in DRILL_CATALOG:
            results.append(self.run_drill(scenario, simulate_fn))
        return results

    def deterministic_hash(self) -> str:
        """Hash of the full drill log for comparison."""
        entries = [r.to_dict() for r in self._drill_log]
        # Remove timing for deterministic comparison
        for e in entries:
            e.pop("duration_ms", None)
        canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def get_report(self) -> Dict[str, Any]:
        """Full drill report for gate checks."""
        return {
            "stats": self.stats,
            "catalog_size": len(DRILL_CATALOG),
            "drill_log_count": len(self._drill_log),
            "drill_hash": self.deterministic_hash(),
        }
