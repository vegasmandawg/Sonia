"""
v4.0 E3 Unit Tests -- Runtime QoS, Contract Fidelity, Release Discipline
=========================================================================
Tests for runtime_governance.py covering all 10 governance components:
1.  SLO compliance (4 tests)
2.  Rate limiter (4 tests)
3.  Output budget (3 tests)
4.  Schema validation (3 tests)
5.  Config contract fidelity (3 tests)
6.  Dependency lock (3 tests)
7.  Release manifest (3 tests)
8.  Promotion gate coverage (3 tests)
9.  Test strategy compliance (3 tests)
10. Deployment readiness (3 tests)

Total: 32 tests (floor: 30)
"""

import json
import sys
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from runtime_governance import (
    BudgetDimension,
    BudgetEnforcementResult,
    ConfigContractFidelityChecker,
    ConfigDriftDetected,
    DEFAULT_BUDGET_LIMITS,
    DEFAULT_SLO_BUDGETS,
    DependencyIntegrityError,
    DependencyLockVerifier,
    DependencyRecord,
    DeploymentNotReady,
    DeploymentReadinessChecker,
    GateSectionBinding,
    OutputBudgetGovernor,
    PromotionGateCoverageChecker,
    REQUIRED_MANIFEST_FIELDS,
    RateLimitConfig,
    RateLimitExceeded,
    RateLimiterGovernor,
    ReleaseManifestIncomplete,
    ReleaseManifestValidator,
    SchemaAuditResult,
    SchemaValidationGovernor,
    SLOBudget,
    SLOComplianceChecker,
    SLOTier,
    SLOViolation,
    TestSectionMapping,
    TestStrategyComplianceChecker,
)


# ============================================================================
# 1. SLO Compliance (4 tests)
# ============================================================================


class TestSLOCompliance:
    """Tests for per-capability SLO budget validation."""

    def test_within_budget(self):
        """All latencies within SLO -> compliant."""
        checker = SLOComplianceChecker()
        for _ in range(100):
            checker.record_latency("file.read", 50.0)
        result = checker.check_compliance("file.read")
        assert result["compliant"] is True
        assert result["p95_ms"] <= 200.0

    def test_exceeds_p95(self):
        """Latencies exceeding p95 -> non-compliant."""
        checker = SLOComplianceChecker()
        # 95% of values at 300ms (above 200ms p95 limit for file.read)
        for _ in range(100):
            checker.record_latency("file.read", 300.0)
        result = checker.check_compliance("file.read")
        assert result["compliant"] is False
        assert len(result["violations"]) > 0

    def test_check_all_capabilities(self):
        """check_all returns results for all registered budgets."""
        checker = SLOComplianceChecker()
        checker.record_latency("file.read", 10.0)
        checker.record_latency("shell.run", 100.0)
        result = checker.check_all()
        assert "file.read" in result["capabilities"]
        assert "shell.run" in result["capabilities"]

    def test_custom_budget_registration(self):
        """Custom budget can be registered and checked."""
        checker = SLOComplianceChecker()
        checker.register_budget(
            SLOBudget("custom.op", SLOTier.BATCH, 5000.0, 10000.0)
        )
        for _ in range(50):
            checker.record_latency("custom.op", 1000.0)
        result = checker.check_compliance("custom.op")
        assert result["compliant"] is True
        assert result["has_budget"] is True


# ============================================================================
# 2. Rate Limiter (4 tests)
# ============================================================================


class TestRateLimiter:
    """Tests for deterministic token-bucket rate limiting."""

    def test_allows_within_burst(self):
        """Requests within burst size are allowed."""
        limiter = RateLimiterGovernor(RateLimitConfig(1.0, burst_size=5))
        for _ in range(5):
            assert limiter.try_acquire("s1") is True

    def test_rejects_over_burst(self):
        """Requests exceeding burst are rejected."""
        limiter = RateLimiterGovernor(RateLimitConfig(1.0, burst_size=3))
        limiter.try_acquire("s1")
        limiter.try_acquire("s1")
        limiter.try_acquire("s1")
        assert limiter.try_acquire("s1") is False

    def test_acquire_or_raise(self):
        """acquire_or_raise raises RateLimitExceeded."""
        limiter = RateLimiterGovernor(RateLimitConfig(1.0, burst_size=1))
        limiter.try_acquire("s2")
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.acquire_or_raise("s2")
        assert exc_info.value.scope_key == "s2"

    def test_is_deterministic(self):
        """Rate limiter reports deterministic behavior."""
        limiter = RateLimiterGovernor()
        assert limiter.is_deterministic() is True
        stats = limiter.get_stats()
        assert "total_requests" in stats


# ============================================================================
# 3. Output Budget (3 tests)
# ============================================================================


class TestOutputBudget:
    """Tests for cross-dimension budget enforcement."""

    def test_within_budget(self):
        """All dimensions within limits -> all_within_budget."""
        gov = OutputBudgetGovernor()
        result = gov.enforce({
            "output_chars": 2000,
            "context_chars": 5000,
            "tool_calls": 3,
            "vision_frames": 2,
            "memory_entries": 5,
        })
        assert result["all_within_budget"] is True

    def test_exceeds_dimension(self):
        """Exceeding one dimension -> not all within budget."""
        gov = OutputBudgetGovernor()
        result = gov.enforce({
            "output_chars": 10000,  # > 4000 limit
            "tool_calls": 2,
        })
        assert result["all_within_budget"] is False

    def test_dimensions_complete(self):
        """All 5 budget dimensions have limits."""
        gov = OutputBudgetGovernor()
        assert gov.dimensions_complete() is True
        limits = gov.get_limits()
        assert len(limits) == 5


# ============================================================================
# 4. Schema Validation (3 tests)
# ============================================================================


class TestSchemaValidation:
    """Tests for schema validation completeness auditing."""

    def test_complete_schema(self):
        """All fields have validators -> complete."""
        gov = SchemaValidationGovernor()
        gov.register_schema("cfg", ["a", "b", "c"], ["a", "b", "c"])
        result = gov.audit_schema("cfg")
        assert result.complete is True

    def test_missing_validators(self):
        """Missing validators -> incomplete."""
        gov = SchemaValidationGovernor()
        gov.register_schema("cfg", ["a", "b", "c"], ["a"])
        result = gov.audit_schema("cfg")
        assert result.complete is False
        assert "b" in result.missing_validators

    def test_audit_all(self):
        """audit_all checks all registered schemas."""
        gov = SchemaValidationGovernor()
        gov.register_schema("s1", ["a"], ["a"])
        gov.register_schema("s2", ["x", "y"], ["x", "y"])
        result = gov.audit_all()
        assert result["all_complete"] is True
        assert result["schemas_audited"] == 2


# ============================================================================
# 5. Config Contract Fidelity (3 tests)
# ============================================================================


class TestConfigContractFidelity:
    """Tests for config drift detection and contract enforcement."""

    def test_no_drift(self):
        """Same value -> no drift detected."""
        cc = ConfigContractFidelityChecker()
        cc.set_baseline("port", 7000)
        result = cc.check_drift("port", 7000)
        assert result["drifted"] is False

    def test_drift_detected(self):
        """Changed value -> drift detected."""
        cc = ConfigContractFidelityChecker()
        cc.set_baseline("port", 7000)
        result = cc.check_drift("port", 9999)
        assert result["drifted"] is True

    def test_check_all(self):
        """check_all evaluates all baselined fields."""
        cc = ConfigContractFidelityChecker()
        cc.set_baseline("port", 7000)
        cc.set_baseline("name", "sonia")
        result = cc.check_all({"port": 7000, "name": "sonia"})
        assert result["all_stable"] is True
        assert result["total_fields"] == 2


# ============================================================================
# 6. Dependency Lock (3 tests)
# ============================================================================


class TestDependencyLock:
    """Tests for dependency lock integrity verification."""

    def test_valid_manifest(self):
        """All packages pinned -> integrity ok."""
        dlv = DependencyLockVerifier()
        dlv.load_manifest([
            {"name": "fastapi", "version": "0.116.1"},
            {"name": "pydantic", "version": "2.11.7"},
        ])
        result = dlv.verify()
        assert result["integrity_ok"] is True
        assert result["all_pinned"] is True

    def test_unpinned_detected(self):
        """Package without version -> not all pinned."""
        dlv = DependencyLockVerifier()
        dlv.load_manifest([
            {"name": "fastapi", "version": "0.116.1"},
            {"name": "orphan", "version": ""},
        ])
        result = dlv.verify()
        assert result["all_pinned"] is False
        assert result["integrity_ok"] is False

    def test_duplicate_detected(self):
        """Duplicate packages -> integrity issue."""
        dlv = DependencyLockVerifier()
        dlv.load_manifest([
            {"name": "fastapi", "version": "0.116.1"},
            {"name": "fastapi", "version": "0.117.0"},
        ])
        result = dlv.verify()
        assert result["no_duplicates"] is False


# ============================================================================
# 7. Release Manifest (3 tests)
# ============================================================================


class TestReleaseManifest:
    """Tests for release manifest completeness validation."""

    def test_valid_manifest(self):
        """Complete manifest -> valid."""
        rmv = ReleaseManifestValidator()
        manifest = {
            "version": "4.0.0",
            "release_date": "2026-02-16",
            "git_sha": "abc123",
            "gate_report": {"passed": 37, "failed": 0},
            "test_count": 625,
            "artifact_checksums": {"manifest.json": "sha256_hash"},
            "dependency_lock_hash": "sha256_hash",
            "changelog": "v4.0 release",
        }
        result = rmv.validate(manifest)
        assert result["valid"] is True

    def test_missing_fields_raises(self):
        """Missing fields -> ReleaseManifestIncomplete."""
        rmv = ReleaseManifestValidator()
        with pytest.raises(ReleaseManifestIncomplete) as exc_info:
            rmv.validate({"version": "4.0.0"})
        assert len(exc_info.value.missing) >= 5

    def test_required_field_count(self):
        """At least 8 required fields defined."""
        assert len(REQUIRED_MANIFEST_FIELDS) >= 8


# ============================================================================
# 8. Promotion Gate Coverage (3 tests)
# ============================================================================


class TestPromotionGateCoverage:
    """Tests for gate-to-section binding validation."""

    def test_complete_coverage(self):
        """All sections covered -> complete."""
        pgc = PromotionGateCoverageChecker()
        pgc.define_sections(["A", "B", "C"])
        pgc.register_gate("g1", ["A"])
        pgc.register_gate("g2", ["B", "C"])
        result = pgc.check_coverage()
        assert result["complete"] is True

    def test_uncovered_sections(self):
        """Missing section coverage -> incomplete."""
        pgc = PromotionGateCoverageChecker()
        pgc.define_sections(["A", "B", "C"])
        pgc.register_gate("g1", ["A"])
        result = pgc.check_coverage()
        assert result["complete"] is False
        assert "B" in result["uncovered_sections"]

    def test_bindings_export(self):
        """Gate bindings can be exported."""
        pgc = PromotionGateCoverageChecker()
        pgc.register_gate("g1", ["A"])
        bindings = pgc.get_bindings()
        assert len(bindings) == 1
        assert bindings[0]["gate_name"] == "g1"


# ============================================================================
# 9. Test Strategy Compliance (3 tests)
# ============================================================================


class TestTestStrategyCompliance:
    """Tests for section coverage and negative test auditing."""

    def test_full_compliance(self):
        """All sections covered with negative tests -> compliant."""
        tsc = TestStrategyComplianceChecker()
        tsc.define_required_sections(["A", "B"])
        tsc.register_test("test_a.py", ["A"], has_negative_tests=True)
        tsc.register_test("test_b.py", ["B"], has_negative_tests=True)
        result = tsc.check_compliance()
        assert result["section_coverage_complete"] is True
        assert result["negative_coverage_complete"] is True

    def test_missing_negative_tests(self):
        """Section without negative tests -> incomplete."""
        tsc = TestStrategyComplianceChecker()
        tsc.define_required_sections(["A", "B"])
        tsc.register_test("test_a.py", ["A"], has_negative_tests=True)
        tsc.register_test("test_b.py", ["B"], has_negative_tests=False)
        result = tsc.check_compliance()
        assert result["section_coverage_complete"] is True
        assert result["negative_coverage_complete"] is False
        assert "B" in result["missing_negative_tests"]

    def test_uncovered_section(self):
        """Unreferenced section -> not covered."""
        tsc = TestStrategyComplianceChecker()
        tsc.define_required_sections(["A", "B", "C"])
        tsc.register_test("test_a.py", ["A"], has_negative_tests=True)
        result = tsc.check_compliance()
        assert result["section_coverage_complete"] is False


# ============================================================================
# 10. Deployment Readiness (3 tests)
# ============================================================================


class TestDeploymentReadiness:
    """Tests for pre-deployment health and precondition checks."""

    def test_all_checks_pass(self):
        """All checks passed -> ready."""
        drc = DeploymentReadinessChecker()
        for check in drc.REQUIRED_CHECKS:
            drc.record_check(check, True)
        result = drc.evaluate()
        assert result["ready"] is True
        assert result["checks_passed"] == 7

    def test_failed_check_raises(self):
        """Failed check -> DeploymentNotReady."""
        drc = DeploymentReadinessChecker()
        for check in drc.REQUIRED_CHECKS:
            drc.record_check(check, check != "gates_passed")
        with pytest.raises(DeploymentNotReady) as exc_info:
            drc.evaluate()
        assert "gates_passed" in exc_info.value.blockers

    def test_unknown_check_rejected(self):
        """Unknown check name -> ValueError."""
        drc = DeploymentReadinessChecker()
        with pytest.raises(ValueError, match="Unknown deployment check"):
            drc.record_check("invented_check", True)
