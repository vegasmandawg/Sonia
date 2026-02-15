"""Automated incident triage recommendations (v3.3 Epic B).

Maps incident snapshots to deterministic remediation recommendations
based on failure class taxonomy. Designed for operator-facing output
with structured steps, severity, and estimated RTO.

Invariants:
    - Same input always produces same recommendation (deterministic).
    - Unknown failure classes get safe fallback (never silent skip).
    - All recommendations include correlation IDs for traceability.
    - Severity is always one of: low, medium, high, critical, unknown.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class TriageRecommendation:
    """Deterministic triage recommendation for an incident."""
    failure_class: str
    service: str
    correlation_id: str
    severity: str
    action: str
    steps: tuple  # tuple for immutability
    estimated_rto_s: int
    triage_hash: str  # deterministic hash for comparison

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_class": self.failure_class,
            "service": self.service,
            "correlation_id": self.correlation_id,
            "severity": self.severity,
            "action": self.action,
            "steps": list(self.steps),
            "estimated_rto_s": self.estimated_rto_s,
            "triage_hash": self.triage_hash,
        }


# Recommendation knowledge base -- deterministic mapping
TRIAGE_KB = {
    "connection_bootstrap": {
        "severity": "high",
        "action": "check_network_and_restart",
        "steps": (
            "verify service process is running",
            "check port availability",
            "verify DNS resolution",
            "restart service with health verification",
        ),
        "estimated_rto_s": 60,
    },
    "timeout": {
        "severity": "medium",
        "action": "increase_timeout_or_scale",
        "steps": (
            "check current latency metrics",
            "verify resource utilization",
            "consider timeout budget increase",
            "scale if load-related",
        ),
        "estimated_rto_s": 120,
    },
    "circuit_open": {
        "severity": "high",
        "action": "investigate_dependency_and_reset",
        "steps": (
            "check dependency health",
            "review recent failure logs",
            "reset breaker after root cause fix",
            "monitor for recurrence",
        ),
        "estimated_rto_s": 90,
    },
    "policy_denied": {
        "severity": "low",
        "action": "review_policy_configuration",
        "steps": (
            "check tool policy classification",
            "verify confirmation queue state",
            "update policy if misconfigured",
        ),
        "estimated_rto_s": 30,
    },
    "validation_failed": {
        "severity": "low",
        "action": "fix_input_validation",
        "steps": (
            "review validation error details",
            "check input schema compatibility",
            "fix caller or update schema",
        ),
        "estimated_rto_s": 30,
    },
    "execution_error": {
        "severity": "medium",
        "action": "investigate_root_cause",
        "steps": (
            "collect error logs from affected service",
            "check for recent deployments",
            "verify input validation",
            "retry or rollback",
        ),
        "estimated_rto_s": 90,
    },
    "backpressure": {
        "severity": "medium",
        "action": "reduce_load_or_scale",
        "steps": (
            "check rate limit metrics",
            "identify top callers",
            "implement backoff or queue",
            "scale if sustained",
        ),
        "estimated_rto_s": 60,
    },
}

FALLBACK_RECOMMENDATION = {
    "severity": "unknown",
    "action": "manual_investigation",
    "steps": (
        "collect diagnostics snapshot",
        "review recent logs",
        "escalate to on-call",
    ),
    "estimated_rto_s": 300,
}


class TriageRecommender:
    """Generates deterministic triage recommendations from incident snapshots."""

    def __init__(self):
        self._stats = {
            "total_triages": 0,
            "known_class_hits": 0,
            "fallback_hits": 0,
        }

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    def recommend(self, snapshot: Dict[str, Any]) -> TriageRecommendation:
        """Generate a triage recommendation from an incident snapshot.

        Always returns a recommendation (never None). Unknown failure
        classes get a safe fallback.
        """
        fc = snapshot.get("failure_class", "unknown")
        service = snapshot.get("service", "unknown")
        correlation_id = snapshot.get("correlation_id", "")

        kb_entry = TRIAGE_KB.get(fc, FALLBACK_RECOMMENDATION)
        self._stats["total_triages"] += 1
        if fc in TRIAGE_KB:
            self._stats["known_class_hits"] += 1
        else:
            self._stats["fallback_hits"] += 1

        # Deterministic hash for this recommendation
        hash_input = json.dumps({
            "failure_class": fc,
            "service": service,
            "action": kb_entry["action"],
        }, sort_keys=True, separators=(",", ":"))
        triage_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        return TriageRecommendation(
            failure_class=fc,
            service=service,
            correlation_id=correlation_id,
            severity=kb_entry["severity"],
            action=kb_entry["action"],
            steps=kb_entry["steps"],
            estimated_rto_s=kb_entry["estimated_rto_s"],
            triage_hash=triage_hash,
        )

    def batch_recommend(
        self, snapshots: List[Dict[str, Any]]
    ) -> List[TriageRecommendation]:
        """Generate recommendations for multiple snapshots."""
        return [self.recommend(snap) for snap in snapshots]

    def get_report(self) -> Dict[str, Any]:
        """Return triage statistics for gate checks."""
        return {
            "triage_stats": self.stats,
            "known_failure_classes": list(TRIAGE_KB.keys()),
            "fallback_severity": FALLBACK_RECOMMENDATION["severity"],
        }
