"""Post-restore invariant verification (v3.3 Epic B).

Validates that recovery paths restore coherent state without violating
system invariants. Runs a series of checks after any restore operation
to confirm the system is in a known-good state.

Checks:
    - Service state convergence (all services HEALTHY or RECOVERING)
    - Circuit breaker consistency (no stuck OPEN without recent failures)
    - State hash comparison (pre-backup vs post-restore)
    - Dependency graph integrity (no orphan references)
    - DLQ consistency (no phantom entries)
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class VerificationResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass(frozen=True)
class CheckResult:
    """Result of a single verification check."""
    check_name: str
    result: VerificationResult
    detail: str
    duration_ms: float


@dataclass
class RestoreVerification:
    """Complete verification report for a restore operation."""
    restore_id: str
    timestamp: float
    checks: List[CheckResult] = field(default_factory=list)
    overall: VerificationResult = VerificationResult.PASS

    @property
    def passed(self) -> bool:
        return self.overall == VerificationResult.PASS

    def add_check(self, check: CheckResult):
        self.checks.append(check)
        if check.result == VerificationResult.FAIL:
            self.overall = VerificationResult.FAIL
        elif check.result == VerificationResult.WARN and self.overall != VerificationResult.FAIL:
            self.overall = VerificationResult.WARN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restore_id": self.restore_id,
            "timestamp": self.timestamp,
            "overall": self.overall.value,
            "checks": [
                {
                    "check_name": c.check_name,
                    "result": c.result.value,
                    "detail": c.detail,
                    "duration_ms": c.duration_ms,
                }
                for c in self.checks
            ],
            "total_checks": len(self.checks),
            "passed": sum(1 for c in self.checks if c.result == VerificationResult.PASS),
            "failed": sum(1 for c in self.checks if c.result == VerificationResult.FAIL),
            "warnings": sum(1 for c in self.checks if c.result == VerificationResult.WARN),
        }


class RestoreVerifier:
    """Runs post-restore verification checks.

    All checks are deterministic and side-effect free.
    """

    def __init__(self):
        self._check_registry: List[str] = [
            "service_convergence",
            "breaker_consistency",
            "state_hash_comparison",
            "dependency_graph_integrity",
            "dlq_consistency",
        ]

    @property
    def registered_checks(self) -> List[str]:
        return list(self._check_registry)

    def verify_service_convergence(
        self, service_states: Dict[str, str]
    ) -> CheckResult:
        """Check that all services are HEALTHY or RECOVERING (not stuck UNREACHABLE)."""
        t0 = time.monotonic()
        stuck = [
            name for name, state in service_states.items()
            if state in ("unreachable", "unknown")
        ]
        elapsed = (time.monotonic() - t0) * 1000

        if stuck:
            return CheckResult(
                check_name="service_convergence",
                result=VerificationResult.FAIL,
                detail=f"Stuck services: {', '.join(stuck)}",
                duration_ms=elapsed,
            )
        recovering = [n for n, s in service_states.items() if s == "recovering"]
        if recovering:
            return CheckResult(
                check_name="service_convergence",
                result=VerificationResult.WARN,
                detail=f"Still recovering: {', '.join(recovering)}",
                duration_ms=elapsed,
            )
        return CheckResult(
            check_name="service_convergence",
            result=VerificationResult.PASS,
            detail=f"All {len(service_states)} services healthy",
            duration_ms=elapsed,
        )

    def verify_breaker_consistency(
        self, breaker_states: Dict[str, Dict[str, Any]]
    ) -> CheckResult:
        """Check that no breaker is stuck OPEN without recent failures."""
        t0 = time.monotonic()
        stuck_open = []
        for name, state in breaker_states.items():
            if state.get("state") == "open":
                failures = state.get("stats", {}).get("consecutive_failures", 0)
                if failures == 0:
                    stuck_open.append(name)
        elapsed = (time.monotonic() - t0) * 1000

        if stuck_open:
            return CheckResult(
                check_name="breaker_consistency",
                result=VerificationResult.FAIL,
                detail=f"Stuck OPEN with 0 failures: {', '.join(stuck_open)}",
                duration_ms=elapsed,
            )
        return CheckResult(
            check_name="breaker_consistency",
            result=VerificationResult.PASS,
            detail=f"All {len(breaker_states)} breakers consistent",
            duration_ms=elapsed,
        )

    def verify_state_hash(
        self, pre_hash: str, post_hash: str
    ) -> CheckResult:
        """Compare state hashes before backup and after restore."""
        t0 = time.monotonic()
        elapsed = (time.monotonic() - t0) * 1000

        if pre_hash == post_hash:
            return CheckResult(
                check_name="state_hash_comparison",
                result=VerificationResult.PASS,
                detail=f"Hash match: {pre_hash[:16]}...",
                duration_ms=elapsed,
            )
        return CheckResult(
            check_name="state_hash_comparison",
            result=VerificationResult.FAIL,
            detail=f"Hash mismatch: pre={pre_hash[:16]}... post={post_hash[:16]}...",
            duration_ms=elapsed,
        )

    def verify_dependency_graph(
        self, graph: Dict[str, List[str]], known_services: List[str]
    ) -> CheckResult:
        """Check dependency graph has no orphan references."""
        t0 = time.monotonic()
        orphans = []
        for node, deps in graph.items():
            for dep in deps:
                if dep not in graph and dep not in known_services:
                    orphans.append(f"{node}->{dep}")
        elapsed = (time.monotonic() - t0) * 1000

        if orphans:
            return CheckResult(
                check_name="dependency_graph_integrity",
                result=VerificationResult.FAIL,
                detail=f"Orphan references: {', '.join(orphans)}",
                duration_ms=elapsed,
            )
        return CheckResult(
            check_name="dependency_graph_integrity",
            result=VerificationResult.PASS,
            detail=f"Graph intact: {len(graph)} nodes",
            duration_ms=elapsed,
        )

    def verify_dlq_consistency(
        self, dlq_count: int, expected_count: int
    ) -> CheckResult:
        """Check DLQ record count matches expected after restore."""
        t0 = time.monotonic()
        elapsed = (time.monotonic() - t0) * 1000

        if dlq_count == expected_count:
            return CheckResult(
                check_name="dlq_consistency",
                result=VerificationResult.PASS,
                detail=f"DLQ count matches: {dlq_count}",
                duration_ms=elapsed,
            )
        return CheckResult(
            check_name="dlq_consistency",
            result=VerificationResult.FAIL,
            detail=f"DLQ mismatch: expected={expected_count}, actual={dlq_count}",
            duration_ms=elapsed,
        )

    def run_full_verification(
        self,
        restore_id: str,
        service_states: Dict[str, str],
        breaker_states: Dict[str, Dict[str, Any]],
        pre_hash: str,
        post_hash: str,
        dependency_graph: Dict[str, List[str]],
        known_services: List[str],
        dlq_count: int,
        expected_dlq_count: int,
    ) -> RestoreVerification:
        """Run all verification checks and return a complete report."""
        report = RestoreVerification(
            restore_id=restore_id,
            timestamp=time.time(),
        )

        report.add_check(self.verify_service_convergence(service_states))
        report.add_check(self.verify_breaker_consistency(breaker_states))
        report.add_check(self.verify_state_hash(pre_hash, post_hash))
        report.add_check(self.verify_dependency_graph(dependency_graph, known_services))
        report.add_check(self.verify_dlq_consistency(dlq_count, expected_dlq_count))

        return report
