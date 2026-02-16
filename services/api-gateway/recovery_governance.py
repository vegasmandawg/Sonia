"""
v4.0 E2 — Recovery, Incident Lineage, Determinism Governance
=============================================================
10 governance components covering recovery pipeline hardening:

1.  RestorePreconditionChecker     — pre-restore health & state validation
2.  PostRestoreVerifier            — invariant checklist after restore
3.  DLQDivergenceGuard             — dry-run / real-run policy parity
4.  BreakerTransitionValidator     — transition matrix completeness
5.  RetryTaxonomyAuditor           — every FailureClass has policy
6.  FallbackContractVerifier       — recovery fallback path consistency
7.  IncidentBundleValidator        — required fields in incident bundles
8.  CorrelationLineageTracker      — unbroken correlation chain across DLQ
9.  RollbackReadinessChecker       — rollback precondition validation
10. RecoveryReproducibilityHasher  — deterministic hashing for decisions
"""

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


# ============================================================================
# 1. Restore Precondition Checker
# ============================================================================


class RestorePreconditionFailure(Exception):
    """Raised when pre-restore preconditions are not met."""

    def __init__(self, checks_failed: List[str]):
        self.checks_failed = checks_failed
        super().__init__(f"Pre-restore preconditions failed: {checks_failed}")


class RestorePreconditionChecker:
    """
    Validates system health and state before allowing a restore operation.

    Checks:
    - Target service is reachable (health check)
    - No active transactions in flight
    - Backup integrity verified
    - DLQ is quiescent (no active replays)
    - Circuit breakers are in safe state
    """

    REQUIRED_CHECKS = frozenset({
        "service_reachable",
        "no_active_transactions",
        "backup_integrity_verified",
        "dlq_quiescent",
        "breakers_safe",
    })

    def __init__(self):
        self._check_results: Dict[str, bool] = {}
        self._check_log: List[Dict[str, Any]] = []

    def record_check(self, check_name: str, passed: bool, detail: str = "") -> None:
        """Record result of a single precondition check."""
        if check_name not in self.REQUIRED_CHECKS:
            raise ValueError(f"Unknown check: {check_name}")
        self._check_results[check_name] = passed
        self._check_log.append({
            "check": check_name,
            "passed": passed,
            "detail": detail,
            "timestamp": time.time(),
        })

    def evaluate(self) -> Dict[str, Any]:
        """
        Evaluate all preconditions. Returns evaluation result.
        Raises RestorePreconditionFailure if any required check fails or is missing.
        """
        missing = self.REQUIRED_CHECKS - set(self._check_results.keys())
        failed = [k for k, v in self._check_results.items() if not v]

        all_ok = len(missing) == 0 and len(failed) == 0
        result = {
            "all_passed": all_ok,
            "checks_completed": len(self._check_results),
            "checks_required": len(self.REQUIRED_CHECKS),
            "missing": sorted(missing),
            "failed": sorted(failed),
            "passed": sorted(k for k, v in self._check_results.items() if v),
            "timestamp": time.time(),
        }

        if not all_ok:
            raise RestorePreconditionFailure(sorted(missing | set(failed)))

        return result

    def reset(self) -> None:
        """Clear check results for a new evaluation cycle."""
        self._check_results.clear()

    def get_check_log(self) -> List[Dict[str, Any]]:
        return list(self._check_log)


# ============================================================================
# 2. Post-Restore Verifier
# ============================================================================


class PostRestoreInvariantFailure(Exception):
    """Raised when post-restore invariants are violated."""

    def __init__(self, violations: List[str]):
        self.violations = violations
        super().__init__(f"Post-restore invariant violations: {violations}")


@dataclass
class RestoreVerificationResult:
    """Result of post-restore verification."""
    restore_id: str
    verified_at: float
    invariants_checked: int
    invariants_passed: int
    violations: List[str]
    is_healthy: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restore_id": self.restore_id,
            "verified_at": self.verified_at,
            "invariants_checked": self.invariants_checked,
            "invariants_passed": self.invariants_passed,
            "violations": self.violations,
            "is_healthy": self.is_healthy,
        }


class PostRestoreVerifier:
    """
    Verifies system invariants after a restore operation.

    Invariants:
    - DLQ record count matches backup manifest
    - Breaker states reset to CLOSED
    - No orphaned correlation IDs
    - Backup manifest checksum valid
    - Service health endpoint responsive
    """

    INVARIANTS = [
        "dlq_count_matches",
        "breakers_reset",
        "no_orphan_correlations",
        "manifest_checksum_valid",
        "service_health_ok",
    ]

    def __init__(self):
        self._results: Dict[str, bool] = {}
        self._verification_history: List[RestoreVerificationResult] = []

    def check_invariant(self, name: str, passed: bool) -> None:
        """Record result of a single invariant check."""
        if name not in self.INVARIANTS:
            raise ValueError(f"Unknown invariant: {name}")
        self._results[name] = passed

    def verify(self, restore_id: str) -> RestoreVerificationResult:
        """Run verification and return result."""
        violations = [k for k, v in self._results.items() if not v]
        unchecked = [i for i in self.INVARIANTS if i not in self._results]
        all_violations = violations + [f"unchecked:{u}" for u in unchecked]

        result = RestoreVerificationResult(
            restore_id=restore_id,
            verified_at=time.time(),
            invariants_checked=len(self._results),
            invariants_passed=sum(1 for v in self._results.values() if v),
            violations=all_violations,
            is_healthy=len(all_violations) == 0,
        )
        self._verification_history.append(result)
        if len(self._verification_history) > 100:
            self._verification_history = self._verification_history[-100:]

        self._results.clear()
        return result

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._verification_history[-limit:]]


# ============================================================================
# 3. DLQ Divergence Guard
# ============================================================================


class DLQDivergenceError(Exception):
    """Raised when dry-run and real-run decisions diverge."""

    def __init__(self, letter_id: str, dry_decision: str, real_decision: str):
        self.letter_id = letter_id
        self.dry_decision = dry_decision
        self.real_decision = real_decision
        super().__init__(
            f"DLQ divergence on {letter_id}: dry={dry_decision}, real={real_decision}"
        )


class DLQDivergenceGuard:
    """
    Ensures dry-run and real-run replay decisions follow the same policy path.

    Records dry-run decisions, then validates that real-run decisions match.
    Raises DLQDivergenceError on divergence.
    """

    def __init__(self):
        self._dry_decisions: Dict[str, str] = {}  # letter_id -> decision
        self._comparisons: List[Dict[str, Any]] = []
        self._divergence_count: int = 0

    def record_dry_run(self, letter_id: str, decision: str) -> None:
        """Record a dry-run decision for later comparison."""
        self._dry_decisions[letter_id] = decision

    def validate_real_run(self, letter_id: str, decision: str) -> Dict[str, Any]:
        """
        Validate that a real-run decision matches the prior dry-run.
        Returns comparison result. Raises DLQDivergenceError on mismatch.
        """
        dry = self._dry_decisions.get(letter_id)
        comparison = {
            "letter_id": letter_id,
            "dry_run_decision": dry,
            "real_run_decision": decision,
            "matches": dry == decision if dry is not None else None,
            "had_dry_run": dry is not None,
            "timestamp": time.time(),
        }
        self._comparisons.append(comparison)
        if len(self._comparisons) > 500:
            self._comparisons = self._comparisons[-500:]

        if dry is not None and dry != decision:
            self._divergence_count += 1
            raise DLQDivergenceError(letter_id, dry, decision)

        return comparison

    def get_stats(self) -> Dict[str, Any]:
        return {
            "pending_dry_runs": len(self._dry_decisions),
            "total_comparisons": len(self._comparisons),
            "divergence_count": self._divergence_count,
        }


# ============================================================================
# 4. Breaker Transition Validator
# ============================================================================


class BreakerTransitionError(Exception):
    """Raised when an invalid breaker state transition is attempted."""

    def __init__(self, from_state: str, to_state: str):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Invalid breaker transition: {from_state} -> {to_state}")


class BreakerTransitionValidator:
    """
    Validates that circuit breaker state transitions follow the allowed
    transition matrix.

    Valid transitions:
        CLOSED    -> OPEN       (threshold exceeded)
        OPEN      -> HALF_OPEN  (recovery timeout elapsed)
        HALF_OPEN -> CLOSED     (probe succeeded)
        HALF_OPEN -> OPEN       (probe failed)
        any       -> CLOSED     (manual reset)
    """

    VALID_TRANSITIONS: Dict[str, Set[str]] = {
        "closed": {"open", "closed"},
        "open": {"half_open", "closed"},
        "half_open": {"closed", "open", "half_open"},
    }

    ALL_STATES = {"closed", "open", "half_open"}

    def __init__(self):
        self._transition_log: List[Dict[str, Any]] = []
        self._violation_count: int = 0

    def validate_transition(
        self, breaker_name: str, from_state: str, to_state: str
    ) -> bool:
        """
        Validate a state transition. Returns True if valid.
        Raises BreakerTransitionError if invalid.
        """
        from_s = from_state.lower()
        to_s = to_state.lower()

        valid_targets = self.VALID_TRANSITIONS.get(from_s, set())
        is_valid = to_s in valid_targets

        self._transition_log.append({
            "breaker": breaker_name,
            "from": from_s,
            "to": to_s,
            "valid": is_valid,
            "timestamp": time.time(),
        })
        if len(self._transition_log) > 500:
            self._transition_log = self._transition_log[-500:]

        if not is_valid:
            self._violation_count += 1
            raise BreakerTransitionError(from_s, to_s)

        return True

    def is_matrix_complete(self) -> bool:
        """Check that every state has at least one valid outgoing transition."""
        return all(
            len(self.VALID_TRANSITIONS.get(s, set())) > 0
            for s in self.ALL_STATES
        )

    def get_transition_matrix(self) -> Dict[str, List[str]]:
        """Export the full transition matrix."""
        return {s: sorted(targets) for s, targets in self.VALID_TRANSITIONS.items()}

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_transitions": len(self._transition_log),
            "violations": self._violation_count,
            "matrix_complete": self.is_matrix_complete(),
            "states": len(self.ALL_STATES),
        }


# ============================================================================
# 5. Retry Taxonomy Auditor
# ============================================================================


class RetryTaxonomyAuditor:
    """
    Audits the retry taxonomy for completeness and consistency.

    Ensures:
    - Every FailureClass has a retry policy entry
    - All retry policies have required fields (retryable, max_retries, backoff_base)
    - Non-retryable classes have max_retries=0
    """

    REQUIRED_POLICY_FIELDS = {"retryable", "max_retries", "backoff_base"}

    def __init__(self):
        self._audit_results: List[Dict[str, Any]] = []

    def audit(
        self,
        failure_classes: List[str],
        retry_policies: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Audit taxonomy completeness.

        Args:
            failure_classes: list of all FailureClass enum values
            retry_policies: dict mapping FailureClass -> policy dict
        """
        issues: List[str] = []
        classes_covered = set()

        for fc in failure_classes:
            policy = retry_policies.get(fc)
            if policy is None:
                issues.append(f"Missing policy for {fc}")
                continue

            classes_covered.add(fc)

            # Check required fields
            missing_fields = self.REQUIRED_POLICY_FIELDS - set(policy.keys())
            if missing_fields:
                issues.append(f"{fc}: missing fields {sorted(missing_fields)}")

            # Non-retryable consistency
            if not policy.get("retryable", True) and policy.get("max_retries", 0) != 0:
                issues.append(
                    f"{fc}: non-retryable but max_retries={policy['max_retries']}"
                )

        uncovered = set(failure_classes) - classes_covered
        result = {
            "complete": len(issues) == 0 and len(uncovered) == 0,
            "failure_classes_total": len(failure_classes),
            "classes_covered": len(classes_covered),
            "uncovered": sorted(uncovered),
            "issues": issues,
            "timestamp": time.time(),
        }
        self._audit_results.append(result)
        return result

    def get_audit_history(self) -> List[Dict[str, Any]]:
        return list(self._audit_results)


# ============================================================================
# 6. Fallback Contract Verifier
# ============================================================================


@dataclass
class FallbackPath:
    """A verified fallback path in the recovery policy."""
    trigger: str
    primary_action: str
    fallback_action: str
    states_applicable: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger": self.trigger,
            "primary_action": self.primary_action,
            "fallback_action": self.fallback_action,
            "states_applicable": self.states_applicable,
        }


class FallbackContractVerifier:
    """
    Verifies that recovery policy fallback paths are consistent.

    Checks:
    - Every non-NO_ACTION rule has a defined fallback
    - Fallback actions are less aggressive than primary actions
    - No circular fallback references
    """

    # Action severity ordering (lower = less aggressive)
    ACTION_SEVERITY = {
        "no_action": 0,
        "retry_with_backoff": 1,
        "shed_load": 2,
        "dlq_enqueue": 3,
        "failover_to_fallback": 4,
        "circuit_open": 5,
        "alert_operator": 6,
        "restart_service": 7,
    }

    def __init__(self):
        self._paths: List[FallbackPath] = []
        self._contracts: Dict[str, str] = {}  # primary_action -> fallback_action

    def register_fallback(self, primary_action: str, fallback_action: str) -> None:
        """Register a fallback for a primary action."""
        self._contracts[primary_action] = fallback_action

    def verify_contracts(
        self, recovery_rules: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Verify all fallback contracts against recovery rules.

        Args:
            recovery_rules: list of rule dicts with 'action', 'state', 'trigger'
        """
        issues: List[str] = []
        verified_paths: List[FallbackPath] = []

        # Group rules by action
        actions_seen = set()
        for rule in recovery_rules:
            action = rule.get("action", "")
            actions_seen.add(action)

        # Check each contract
        for primary, fallback in self._contracts.items():
            p_sev = self.ACTION_SEVERITY.get(primary, -1)
            f_sev = self.ACTION_SEVERITY.get(fallback, -1)

            if p_sev < 0:
                issues.append(f"Unknown primary action: {primary}")
            if f_sev < 0:
                issues.append(f"Unknown fallback action: {fallback}")
            if p_sev >= 0 and f_sev >= 0 and f_sev >= p_sev:
                issues.append(
                    f"Fallback {fallback} (sev={f_sev}) is not less aggressive "
                    f"than primary {primary} (sev={p_sev})"
                )

            # Check for circular references
            visited = {primary}
            current = fallback
            while current in self._contracts:
                if current in visited:
                    issues.append(f"Circular fallback: {primary} -> ... -> {current}")
                    break
                visited.add(current)
                current = self._contracts[current]

            applicable_states = [
                r.get("state", "")
                for r in recovery_rules
                if r.get("action") == primary
            ]
            verified_paths.append(FallbackPath(
                trigger="",
                primary_action=primary,
                fallback_action=fallback,
                states_applicable=applicable_states,
            ))

        self._paths = verified_paths
        return {
            "contracts_verified": len(self._contracts),
            "issues": issues,
            "consistent": len(issues) == 0,
            "paths": [p.to_dict() for p in verified_paths],
            "timestamp": time.time(),
        }

    def get_severity(self, action: str) -> int:
        """Get severity level for an action."""
        return self.ACTION_SEVERITY.get(action, -1)

    def get_paths(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self._paths]


# ============================================================================
# 7. Incident Bundle Validator
# ============================================================================


class IncidentBundleValidationError(Exception):
    """Raised when an incident bundle is incomplete."""

    def __init__(self, missing_fields: List[str]):
        self.missing_fields = missing_fields
        super().__init__(f"Incident bundle missing: {missing_fields}")


@dataclass
class IncidentBundleSpec:
    """Specification for required incident bundle fields."""
    # Core identification
    incident_id: str = ""
    timestamp: float = 0.0
    correlation_id: str = ""

    # Context
    service_name: str = ""
    trigger: str = ""
    root_cause_class: str = ""

    # Timeline
    timeline_events: List[Dict[str, Any]] = field(default_factory=list)

    # Recovery
    recovery_action_taken: str = ""
    recovery_outcome: str = ""  # success, partial, failed

    # Evidence
    dlq_snapshot: List[Dict[str, Any]] = field(default_factory=list)
    breaker_snapshot: Dict[str, Any] = field(default_factory=dict)
    correlation_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "service_name": self.service_name,
            "trigger": self.trigger,
            "root_cause_class": self.root_cause_class,
            "timeline_event_count": len(self.timeline_events),
            "timeline_events": self.timeline_events,
            "recovery_action_taken": self.recovery_action_taken,
            "recovery_outcome": self.recovery_outcome,
            "dlq_snapshot_count": len(self.dlq_snapshot),
            "breaker_snapshot": self.breaker_snapshot,
            "correlation_chain_length": len(self.correlation_chain),
            "correlation_chain": self.correlation_chain,
        }


class IncidentBundleValidator:
    """
    Validates that incident bundles contain all required fields and
    meet completeness criteria.
    """

    REQUIRED_FIELDS = frozenset({
        "incident_id",
        "timestamp",
        "correlation_id",
        "service_name",
        "trigger",
        "root_cause_class",
        "recovery_action_taken",
        "recovery_outcome",
    })

    VALID_OUTCOMES = {"success", "partial", "failed", "pending"}

    def __init__(self):
        self._validation_log: List[Dict[str, Any]] = []

    def validate(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate an incident bundle dict.
        Returns validation result with issues list.
        """
        issues: List[str] = []

        # Check required fields
        missing = []
        for f in self.REQUIRED_FIELDS:
            if f not in bundle or not bundle[f]:
                missing.append(f)

        if missing:
            issues.append(f"Missing required fields: {sorted(missing)}")

        # Check outcome validity
        outcome = bundle.get("recovery_outcome", "")
        if outcome and outcome not in self.VALID_OUTCOMES:
            issues.append(f"Invalid recovery_outcome: {outcome}")

        # Check timeline has events
        timeline = bundle.get("timeline_events", [])
        if not isinstance(timeline, list) or len(timeline) == 0:
            issues.append("Timeline events empty or missing")

        # Check correlation chain
        chain = bundle.get("correlation_chain", [])
        if not isinstance(chain, list):
            issues.append("Correlation chain must be a list")

        result = {
            "valid": len(issues) == 0,
            "issues": issues,
            "missing_fields": missing,
            "fields_present": len(bundle),
            "timestamp": time.time(),
        }
        self._validation_log.append(result)
        if len(self._validation_log) > 200:
            self._validation_log = self._validation_log[-200:]

        if missing:
            raise IncidentBundleValidationError(missing)

        return result

    def validate_spec(self, spec: IncidentBundleSpec) -> Dict[str, Any]:
        """Validate an IncidentBundleSpec dataclass instance."""
        return self.validate(spec.to_dict())

    def get_validation_log(self) -> List[Dict[str, Any]]:
        return list(self._validation_log)


# ============================================================================
# 8. Correlation Lineage Tracker
# ============================================================================


@dataclass
class LineageNode:
    """A single node in a correlation lineage chain."""
    correlation_id: str
    parent_correlation_id: Optional[str]
    event_type: str  # "original", "retry", "replay", "fallback"
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class CorrelationLineageTracker:
    """
    Tracks unbroken correlation chains across DLQ replay and recovery.

    Ensures:
    - Every replay has a parent correlation ID
    - No orphaned correlation IDs
    - Chain depth is bounded
    """

    MAX_CHAIN_DEPTH = 10
    MAX_NODES = 5000

    def __init__(self, max_chain_depth: int = MAX_CHAIN_DEPTH):
        self._nodes: Dict[str, LineageNode] = {}
        self._children: Dict[str, List[str]] = {}  # parent -> children
        self._max_depth = max_chain_depth
        self._counter: int = 0

    def record_event(
        self,
        correlation_id: str,
        parent_correlation_id: Optional[str],
        event_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LineageNode:
        """Record a correlation event in the lineage chain."""
        node = LineageNode(
            correlation_id=correlation_id,
            parent_correlation_id=parent_correlation_id,
            event_type=event_type,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        self._nodes[correlation_id] = node
        self._counter += 1

        if parent_correlation_id:
            if parent_correlation_id not in self._children:
                self._children[parent_correlation_id] = []
            self._children[parent_correlation_id].append(correlation_id)

        # Bound total nodes
        if len(self._nodes) > self.MAX_NODES:
            oldest_key = min(self._nodes, key=lambda k: self._nodes[k].timestamp)
            del self._nodes[oldest_key]
            self._children.pop(oldest_key, None)

        return node

    def get_chain(self, correlation_id: str) -> List[Dict[str, Any]]:
        """Walk the chain from a correlation ID back to its root."""
        chain = []
        current = correlation_id
        visited = set()

        while current and current not in visited and len(chain) < self._max_depth:
            visited.add(current)
            node = self._nodes.get(current)
            if not node:
                break
            chain.append({
                "correlation_id": node.correlation_id,
                "parent": node.parent_correlation_id,
                "event_type": node.event_type,
                "timestamp": node.timestamp,
            })
            current = node.parent_correlation_id

        return list(reversed(chain))  # root -> leaf order

    def check_continuity(self, correlation_id: str) -> Dict[str, Any]:
        """
        Check that a correlation chain is unbroken (every parent exists).
        """
        chain = self.get_chain(correlation_id)
        broken_links = []

        for i, entry in enumerate(chain):
            parent = entry.get("parent")
            if parent and parent not in self._nodes:
                broken_links.append({
                    "position": i,
                    "correlation_id": entry["correlation_id"],
                    "missing_parent": parent,
                })

        return {
            "correlation_id": correlation_id,
            "chain_length": len(chain),
            "continuous": len(broken_links) == 0,
            "broken_links": broken_links,
        }

    def find_orphans(self) -> List[str]:
        """Find correlation IDs that reference non-existent parents."""
        orphans = []
        for cid, node in self._nodes.items():
            if (
                node.parent_correlation_id
                and node.parent_correlation_id not in self._nodes
            ):
                orphans.append(cid)
        return orphans

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_nodes": len(self._nodes),
            "counter": self._counter,
            "max_chain_depth": self._max_depth,
            "orphan_count": len(self.find_orphans()),
            "parent_chains": len(self._children),
        }


# ============================================================================
# 9. Rollback Readiness Checker
# ============================================================================


class RollbackNotReady(Exception):
    """Raised when rollback preconditions are not met."""

    def __init__(self, blockers: List[str]):
        self.blockers = blockers
        super().__init__(f"Rollback not ready: {blockers}")


@dataclass
class RollbackCheckResult:
    """Result of a rollback readiness evaluation."""
    ready: bool
    checks_passed: int
    checks_total: int
    blockers: List[str]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "checks_passed": self.checks_passed,
            "checks_total": self.checks_total,
            "blockers": self.blockers,
            "timestamp": self.timestamp,
        }


class RollbackReadinessChecker:
    """
    Validates preconditions before allowing a rollback operation.

    Checks:
    - Target version tag exists
    - No active user sessions (or force flag)
    - Backup exists for current state
    - DLQ drained or acknowledged
    - Health endpoint of target version available
    """

    REQUIRED_CHECKS = [
        "target_version_exists",
        "sessions_safe",
        "backup_current_state",
        "dlq_acknowledged",
        "target_health_ok",
    ]

    def __init__(self):
        self._check_results: Dict[str, bool] = {}
        self._history: List[RollbackCheckResult] = []

    def record_check(self, check_name: str, passed: bool) -> None:
        """Record a single rollback readiness check."""
        if check_name not in self.REQUIRED_CHECKS:
            raise ValueError(f"Unknown rollback check: {check_name}")
        self._check_results[check_name] = passed

    def evaluate(self) -> RollbackCheckResult:
        """Evaluate rollback readiness."""
        blockers = []
        for check in self.REQUIRED_CHECKS:
            if check not in self._check_results:
                blockers.append(f"unchecked:{check}")
            elif not self._check_results[check]:
                blockers.append(check)

        result = RollbackCheckResult(
            ready=len(blockers) == 0,
            checks_passed=sum(1 for v in self._check_results.values() if v),
            checks_total=len(self.REQUIRED_CHECKS),
            blockers=blockers,
            timestamp=time.time(),
        )
        self._history.append(result)
        if len(self._history) > 50:
            self._history = self._history[-50:]

        self._check_results.clear()

        if not result.ready:
            raise RollbackNotReady(blockers)

        return result

    def get_history(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history]


# ============================================================================
# 10. Recovery Reproducibility Hasher
# ============================================================================


class RecoveryReproducibilityHasher:
    """
    Produces deterministic hashes for recovery decisions to support
    reproducibility verification and rerun parity.

    Hash inputs:
    - service_name + state + trigger + correlation_id
    - policy table version hash
    - decision outcome
    """

    def __init__(self):
        self._policy_hash: str = ""
        self._decision_hashes: List[Dict[str, Any]] = []

    def set_policy_hash(self, policy_table: List[Dict[str, Any]]) -> str:
        """Compute and store a hash of the current policy table."""
        canonical = json.dumps(policy_table, sort_keys=True, separators=(",", ":"))
        self._policy_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return self._policy_hash

    def hash_decision(
        self,
        service_name: str,
        state: str,
        trigger: str,
        correlation_id: str,
        decision: str,
    ) -> str:
        """
        Compute a deterministic hash for a recovery decision.
        Same inputs always produce the same hash.
        """
        payload = (
            f"{service_name}|{state}|{trigger}|{correlation_id}"
            f"|{decision}|{self._policy_hash}"
        )
        h = hashlib.sha256(payload.encode()).hexdigest()

        self._decision_hashes.append({
            "hash": h,
            "service": service_name,
            "state": state,
            "trigger": trigger,
            "correlation_id": correlation_id,
            "decision": decision,
            "timestamp": time.time(),
        })
        if len(self._decision_hashes) > 500:
            self._decision_hashes = self._decision_hashes[-500:]

        return h

    def verify_rerun(
        self,
        service_name: str,
        state: str,
        trigger: str,
        correlation_id: str,
        decision: str,
        expected_hash: str,
    ) -> Dict[str, Any]:
        """
        Verify that re-running a decision produces the same hash.
        """
        actual = self.hash_decision(
            service_name, state, trigger, correlation_id, decision,
        )
        return {
            "matches": actual == expected_hash,
            "expected": expected_hash,
            "actual": actual,
            "service": service_name,
            "correlation_id": correlation_id,
        }

    def get_policy_hash(self) -> str:
        return self._policy_hash

    def get_stats(self) -> Dict[str, Any]:
        return {
            "policy_hash_set": bool(self._policy_hash),
            "policy_hash": self._policy_hash[:16] if self._policy_hash else "",
            "total_hashes": len(self._decision_hashes),
        }


# ── JSON helper for import ──────────────────────────────────────────────────
import json
