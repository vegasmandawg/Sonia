"""
v4.0 E2 Unit Tests -- Recovery, Incident Lineage, Determinism
==============================================================
Tests for recovery_governance.py covering all 10 governance components:
1.  Restore preconditions (4 tests)
2.  Post-restore verification (4 tests)
3.  DLQ divergence guard (4 tests)
4.  Breaker transition validator (4 tests)
5.  Retry taxonomy auditor (3 tests)
6.  Fallback contract verifier (3 tests)
7.  Incident bundle validator (3 tests)
8.  Correlation lineage tracker (4 tests)
9.  Rollback readiness checker (3 tests)
10. Recovery reproducibility hasher (3 tests)

Total: 35 tests (floor: 30)
"""

import json
import sys
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from recovery_governance import (
    BreakerTransitionError,
    BreakerTransitionValidator,
    CorrelationLineageTracker,
    DLQDivergenceError,
    DLQDivergenceGuard,
    FallbackContractVerifier,
    FallbackPath,
    IncidentBundleSpec,
    IncidentBundleValidationError,
    IncidentBundleValidator,
    LineageNode,
    PostRestoreInvariantFailure,
    PostRestoreVerifier,
    RecoveryReproducibilityHasher,
    RestorePreconditionChecker,
    RestorePreconditionFailure,
    RestoreVerificationResult,
    RetryTaxonomyAuditor,
    RollbackCheckResult,
    RollbackNotReady,
    RollbackReadinessChecker,
)


# ============================================================================
# 1. Restore Preconditions (4 tests)
# ============================================================================


class TestRestorePreconditions:
    """Tests for pre-restore health & state validation."""

    def test_all_checks_pass(self):
        """All preconditions met -> evaluate returns result."""
        checker = RestorePreconditionChecker()
        for check in checker.REQUIRED_CHECKS:
            checker.record_check(check, True)
        result = checker.evaluate()
        assert result["all_passed"] is True
        assert result["checks_completed"] == 5

    def test_missing_check_raises(self):
        """Missing any check -> raises RestorePreconditionFailure."""
        checker = RestorePreconditionChecker()
        checker.record_check("service_reachable", True)
        # Only 1 of 5 recorded
        with pytest.raises(RestorePreconditionFailure) as exc_info:
            checker.evaluate()
        assert len(exc_info.value.checks_failed) == 4

    def test_failed_check_raises(self):
        """A failed check -> raises RestorePreconditionFailure."""
        checker = RestorePreconditionChecker()
        for check in checker.REQUIRED_CHECKS:
            checker.record_check(check, check != "dlq_quiescent")
        with pytest.raises(RestorePreconditionFailure) as exc_info:
            checker.evaluate()
        assert "dlq_quiescent" in exc_info.value.checks_failed

    def test_unknown_check_rejected(self):
        """Unknown check name -> ValueError."""
        checker = RestorePreconditionChecker()
        with pytest.raises(ValueError, match="Unknown check"):
            checker.record_check("invented_check", True)


# ============================================================================
# 2. Post-Restore Verification (4 tests)
# ============================================================================


class TestPostRestoreVerification:
    """Tests for post-restore invariant verification."""

    def test_all_invariants_pass(self):
        """All invariants met -> is_healthy=True."""
        verifier = PostRestoreVerifier()
        for inv in verifier.INVARIANTS:
            verifier.check_invariant(inv, True)
        result = verifier.verify("restore_001")
        assert result.is_healthy is True
        assert result.invariants_passed == 5
        assert len(result.violations) == 0

    def test_failed_invariant(self):
        """Failed invariant -> recorded in violations."""
        verifier = PostRestoreVerifier()
        for inv in verifier.INVARIANTS:
            verifier.check_invariant(inv, inv != "breakers_reset")
        result = verifier.verify("restore_002")
        assert result.is_healthy is False
        assert "breakers_reset" in result.violations

    def test_unchecked_invariant(self):
        """Unchecked invariant -> violation with 'unchecked:' prefix."""
        verifier = PostRestoreVerifier()
        verifier.check_invariant("dlq_count_matches", True)
        result = verifier.verify("restore_003")
        assert result.is_healthy is False
        unchecked = [v for v in result.violations if v.startswith("unchecked:")]
        assert len(unchecked) == 4

    def test_history_tracked(self):
        """Verification history is maintained."""
        verifier = PostRestoreVerifier()
        for inv in verifier.INVARIANTS:
            verifier.check_invariant(inv, True)
        verifier.verify("r1")
        for inv in verifier.INVARIANTS:
            verifier.check_invariant(inv, True)
        verifier.verify("r2")
        history = verifier.get_history()
        assert len(history) == 2
        assert history[0]["restore_id"] == "r1"


# ============================================================================
# 3. DLQ Divergence Guard (4 tests)
# ============================================================================


class TestDLQDivergenceGuard:
    """Tests for dry-run / real-run divergence detection."""

    def test_matching_decisions(self):
        """Dry and real decisions match -> no error."""
        guard = DLQDivergenceGuard()
        guard.record_dry_run("dl_001", "approve")
        result = guard.validate_real_run("dl_001", "approve")
        assert result["matches"] is True

    def test_divergent_decisions_raises(self):
        """Divergent decisions -> raises DLQDivergenceError."""
        guard = DLQDivergenceGuard()
        guard.record_dry_run("dl_002", "approve")
        with pytest.raises(DLQDivergenceError) as exc_info:
            guard.validate_real_run("dl_002", "reject")
        assert exc_info.value.dry_decision == "approve"
        assert exc_info.value.real_decision == "reject"

    def test_no_dry_run_recorded(self):
        """No prior dry run -> comparison has had_dry_run=False."""
        guard = DLQDivergenceGuard()
        result = guard.validate_real_run("dl_003", "approve")
        assert result["had_dry_run"] is False
        assert result["matches"] is None

    def test_stats_track_divergences(self):
        """Stats track total divergences."""
        guard = DLQDivergenceGuard()
        guard.record_dry_run("dl_004", "approve")
        try:
            guard.validate_real_run("dl_004", "reject")
        except DLQDivergenceError:
            pass
        stats = guard.get_stats()
        assert stats["divergence_count"] == 1


# ============================================================================
# 4. Breaker Transition Validator (4 tests)
# ============================================================================


class TestBreakerTransitionValidator:
    """Tests for circuit breaker transition matrix validation."""

    def test_valid_transition(self):
        """CLOSED->OPEN is a valid transition."""
        v = BreakerTransitionValidator()
        assert v.validate_transition("breaker_1", "closed", "open") is True

    def test_invalid_transition_raises(self):
        """CLOSED->HALF_OPEN is invalid (must go through OPEN first)."""
        v = BreakerTransitionValidator()
        with pytest.raises(BreakerTransitionError) as exc_info:
            v.validate_transition("breaker_1", "closed", "half_open")
        assert exc_info.value.from_state == "closed"
        assert exc_info.value.to_state == "half_open"

    def test_matrix_complete(self):
        """Transition matrix covers all 3 states."""
        v = BreakerTransitionValidator()
        assert v.is_matrix_complete() is True
        matrix = v.get_transition_matrix()
        assert len(matrix) == 3

    def test_stats_track_violations(self):
        """Stats count transition violations."""
        v = BreakerTransitionValidator()
        try:
            v.validate_transition("b", "closed", "half_open")
        except BreakerTransitionError:
            pass
        v.validate_transition("b", "closed", "open")
        stats = v.get_stats()
        assert stats["violations"] == 1
        assert stats["total_transitions"] == 2


# ============================================================================
# 5. Retry Taxonomy Auditor (3 tests)
# ============================================================================


class TestRetryTaxonomyAuditor:
    """Tests for retry taxonomy completeness auditing."""

    def test_complete_taxonomy(self):
        """All failure classes have valid policies -> complete."""
        auditor = RetryTaxonomyAuditor()
        classes = ["conn", "timeout", "policy"]
        policies = {
            "conn": {"retryable": True, "max_retries": 3, "backoff_base": 2.0},
            "timeout": {"retryable": True, "max_retries": 2, "backoff_base": 1.5},
            "policy": {"retryable": False, "max_retries": 0, "backoff_base": 0},
        }
        result = auditor.audit(classes, policies)
        assert result["complete"] is True
        assert result["classes_covered"] == 3

    def test_missing_policy_detected(self):
        """Missing policy for a failure class -> incomplete."""
        auditor = RetryTaxonomyAuditor()
        classes = ["conn", "timeout"]
        policies = {"conn": {"retryable": True, "max_retries": 3, "backoff_base": 2.0}}
        result = auditor.audit(classes, policies)
        assert result["complete"] is False
        assert "timeout" in result["uncovered"]

    def test_inconsistency_detected(self):
        """Non-retryable with max_retries>0 -> issue reported."""
        auditor = RetryTaxonomyAuditor()
        classes = ["bad"]
        policies = {"bad": {"retryable": False, "max_retries": 5, "backoff_base": 0}}
        result = auditor.audit(classes, policies)
        assert result["complete"] is False
        assert any("non-retryable" in issue for issue in result["issues"])


# ============================================================================
# 6. Fallback Contract Verifier (3 tests)
# ============================================================================


class TestFallbackContractVerifier:
    """Tests for recovery fallback path consistency."""

    def test_valid_fallback(self):
        """Less aggressive fallback -> consistent."""
        v = FallbackContractVerifier()
        v.register_fallback("restart_service", "dlq_enqueue")
        rules = [{"action": "restart_service", "state": "failed", "trigger": "crash"}]
        result = v.verify_contracts(rules)
        assert result["consistent"] is True

    def test_aggressive_fallback_detected(self):
        """Fallback more aggressive than primary -> inconsistent."""
        v = FallbackContractVerifier()
        v.register_fallback("retry_with_backoff", "restart_service")
        rules = [{"action": "retry_with_backoff", "state": "healthy", "trigger": "timeout"}]
        result = v.verify_contracts(rules)
        assert result["consistent"] is False
        assert any("not less aggressive" in i for i in result["issues"])

    def test_severity_ordering(self):
        """Action severity ordering is consistent."""
        v = FallbackContractVerifier()
        assert v.get_severity("no_action") < v.get_severity("restart_service")
        assert v.get_severity("retry_with_backoff") < v.get_severity("circuit_open")


# ============================================================================
# 7. Incident Bundle Validator (3 tests)
# ============================================================================


class TestIncidentBundleValidator:
    """Tests for incident bundle completeness validation."""

    def test_valid_bundle(self):
        """Complete bundle -> valid."""
        v = IncidentBundleValidator()
        bundle = {
            "incident_id": "inc_001",
            "timestamp": time.time(),
            "correlation_id": "req_abc",
            "service_name": "api-gateway",
            "trigger": "timeout",
            "root_cause_class": "timeout",
            "recovery_action_taken": "retry",
            "recovery_outcome": "success",
            "timeline_events": [{"event": "start"}],
            "correlation_chain": ["req_abc"],
        }
        result = v.validate(bundle)
        assert result["valid"] is True

    def test_missing_fields_raises(self):
        """Missing required fields -> IncidentBundleValidationError."""
        v = IncidentBundleValidator()
        bundle = {"incident_id": "inc_002"}
        with pytest.raises(IncidentBundleValidationError) as exc_info:
            v.validate(bundle)
        assert len(exc_info.value.missing_fields) >= 5

    def test_spec_validation(self):
        """IncidentBundleSpec can be validated."""
        v = IncidentBundleValidator()
        spec = IncidentBundleSpec(
            incident_id="inc_003",
            timestamp=time.time(),
            correlation_id="req_xyz",
            service_name="api-gateway",
            trigger="crash",
            root_cause_class="execution_error",
            timeline_events=[{"event": "crash_detected"}],
            recovery_action_taken="restart",
            recovery_outcome="success",
            correlation_chain=["req_xyz"],
        )
        result = v.validate_spec(spec)
        assert result["valid"] is True


# ============================================================================
# 8. Correlation Lineage Tracker (4 tests)
# ============================================================================


class TestCorrelationLineageTracker:
    """Tests for correlation chain tracking."""

    def test_chain_construction(self):
        """Chain builds correctly from root to leaf."""
        tracker = CorrelationLineageTracker()
        tracker.record_event("c1", None, "original")
        tracker.record_event("c2", "c1", "retry")
        tracker.record_event("c3", "c2", "replay")
        chain = tracker.get_chain("c3")
        assert len(chain) == 3
        assert chain[0]["correlation_id"] == "c1"
        assert chain[2]["correlation_id"] == "c3"

    def test_continuity_check_valid(self):
        """Unbroken chain -> continuous=True."""
        tracker = CorrelationLineageTracker()
        tracker.record_event("c1", None, "original")
        tracker.record_event("c2", "c1", "retry")
        result = tracker.check_continuity("c2")
        assert result["continuous"] is True
        assert result["chain_length"] == 2

    def test_continuity_check_broken(self):
        """Missing parent -> broken link detected."""
        tracker = CorrelationLineageTracker()
        # c2 references c1, but c1 doesn't exist
        tracker.record_event("c2", "c1", "retry")
        result = tracker.check_continuity("c2")
        assert result["continuous"] is False
        assert len(result["broken_links"]) == 1

    def test_orphan_detection(self):
        """Orphaned nodes (referencing missing parents) are found."""
        tracker = CorrelationLineageTracker()
        tracker.record_event("c1", None, "original")
        tracker.record_event("c2", "c1", "retry")
        tracker.record_event("c3", "missing_parent", "replay")
        orphans = tracker.find_orphans()
        assert "c3" in orphans
        assert "c2" not in orphans


# ============================================================================
# 9. Rollback Readiness Checker (3 tests)
# ============================================================================


class TestRollbackReadinessChecker:
    """Tests for rollback precondition validation."""

    def test_all_checks_pass(self):
        """All checks passed -> ready."""
        checker = RollbackReadinessChecker()
        for check in checker.REQUIRED_CHECKS:
            checker.record_check(check, True)
        result = checker.evaluate()
        assert result.ready is True
        assert result.checks_passed == 5

    def test_failed_check_raises(self):
        """Failed check -> RollbackNotReady."""
        checker = RollbackReadinessChecker()
        for check in checker.REQUIRED_CHECKS:
            checker.record_check(check, check != "dlq_acknowledged")
        with pytest.raises(RollbackNotReady) as exc_info:
            checker.evaluate()
        assert "dlq_acknowledged" in exc_info.value.blockers

    def test_unchecked_blocker(self):
        """Unchecked items appear as blockers."""
        checker = RollbackReadinessChecker()
        checker.record_check("target_version_exists", True)
        with pytest.raises(RollbackNotReady) as exc_info:
            checker.evaluate()
        blockers = exc_info.value.blockers
        unchecked = [b for b in blockers if b.startswith("unchecked:")]
        assert len(unchecked) == 4


# ============================================================================
# 10. Recovery Reproducibility Hasher (3 tests)
# ============================================================================


class TestRecoveryReproducibilityHasher:
    """Tests for deterministic recovery decision hashing."""

    def test_deterministic_hash(self):
        """Same inputs -> same hash."""
        hasher = RecoveryReproducibilityHasher()
        hasher.set_policy_hash([{"rule": "test"}])
        h1 = hasher.hash_decision("svc", "healthy", "timeout", "req_1", "retry")
        h2 = hasher.hash_decision("svc", "healthy", "timeout", "req_1", "retry")
        assert h1 == h2
        assert len(h1) == 64

    def test_different_inputs_different_hash(self):
        """Different correlation_id -> different hash."""
        hasher = RecoveryReproducibilityHasher()
        hasher.set_policy_hash([{"rule": "test"}])
        h1 = hasher.hash_decision("svc", "healthy", "timeout", "req_1", "retry")
        h2 = hasher.hash_decision("svc", "healthy", "timeout", "req_2", "retry")
        assert h1 != h2

    def test_verify_rerun(self):
        """Rerun verification matches original hash."""
        hasher = RecoveryReproducibilityHasher()
        hasher.set_policy_hash([{"rule": "test"}])
        h1 = hasher.hash_decision("svc", "degraded", "crash", "req_x", "restart")
        result = hasher.verify_rerun("svc", "degraded", "crash", "req_x", "restart", h1)
        assert result["matches"] is True
        # Different decision -> mismatch
        result2 = hasher.verify_rerun("svc", "degraded", "crash", "req_x", "dlq", h1)
        assert result2["matches"] is False
