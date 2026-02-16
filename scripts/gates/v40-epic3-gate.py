"""
v4.0 Epic 3 Gate -- Runtime QoS, Contract Fidelity, Release Discipline
=======================================================================
10 concrete checks validating E3 modules exist and pass structural invariants.

Exit 0 = PASS, exit 1 = FAIL.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path("S:/")
GATEWAY = REPO_ROOT / "services" / "api-gateway"

checks = []


def check(name, passed, detail=""):
    checks.append({"name": name, "passed": passed, "detail": detail})
    tag = "PASS" if passed else "FAIL"
    print(f"  [{tag}] {name}: {detail}")


def load_module(name, path):
    """Load a Python module by path without polluting sys.modules."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None
    finally:
        sys.modules.pop(name, None)


# ---- Load E3 governance module ------------------------------------------------
print("=== v4.0 Epic 3 Gate: Runtime QoS, Contract Fidelity, Release ===\n")

gov_path = GATEWAY / "runtime_governance.py"
gov = load_module("runtime_governance", gov_path)

# ---- Check 1: Per-capability SLO compliance -----------------------------------
has_slo = (gov is not None
           and hasattr(gov, "SLOComplianceChecker")
           and hasattr(gov, "SLOBudget")
           and hasattr(gov, "SLOTier"))
if has_slo:
    checker = gov.SLOComplianceChecker()
    has_slo = (
        hasattr(checker, "check_compliance")
        and hasattr(checker, "check_all")
        and len(gov.DEFAULT_SLO_BUDGETS) >= 6
        and len(gov.SLOTier) == 4
    )
check(
    "per_capability_slo_compliance",
    has_slo,
    f"SLOComplianceChecker with {len(getattr(gov, 'DEFAULT_SLO_BUDGETS', {}))} budgets, {len(getattr(gov, 'SLOTier', []))} tiers"
    if has_slo else "SLOComplianceChecker missing or incomplete",
)

# ---- Check 2: Rate limiter determinism ----------------------------------------
has_rate = (gov is not None
            and hasattr(gov, "RateLimiterGovernor")
            and hasattr(gov, "RateLimitExceeded"))
if has_rate:
    limiter = gov.RateLimiterGovernor(
        gov.RateLimitConfig(tokens_per_second=1.0, burst_size=2)
    )
    has_rate = (
        limiter.is_deterministic()
        and hasattr(limiter, "try_acquire")
        and hasattr(limiter, "acquire_or_raise")
    )
    if has_rate:
        # Verify deterministic behavior: exhaust tokens, then fail
        assert limiter.try_acquire("test", 1.0) is True
        assert limiter.try_acquire("test", 1.0) is True
        assert limiter.try_acquire("test", 1.0) is False  # burst exhausted
check(
    "rate_limiter_determinism",
    has_rate,
    "RateLimiterGovernor: deterministic token-bucket verified"
    if has_rate else "RateLimiterGovernor missing or non-deterministic",
)

# ---- Check 3: Output budget enforcement ---------------------------------------
has_budget = (gov is not None
              and hasattr(gov, "OutputBudgetGovernor")
              and hasattr(gov, "BudgetDimension"))
if has_budget:
    budget_gov = gov.OutputBudgetGovernor()
    has_budget = (
        budget_gov.dimensions_complete()
        and len(gov.BudgetDimension) == 5
        and hasattr(budget_gov, "enforce")
    )
check(
    "output_budget_enforcement",
    has_budget,
    f"OutputBudgetGovernor with {len(getattr(gov, 'BudgetDimension', []))} dimensions"
    if has_budget else "OutputBudgetGovernor missing or incomplete",
)

# ---- Check 4: Schema validation completeness ----------------------------------
has_schema = (gov is not None
              and hasattr(gov, "SchemaValidationGovernor")
              and hasattr(gov, "SchemaAuditResult"))
if has_schema:
    sv = gov.SchemaValidationGovernor()
    sv.register_schema("test", ["f1", "f2", "f3"], ["f1", "f2", "f3"])
    result = sv.audit_schema("test")
    has_schema = result.complete and hasattr(sv, "audit_all")
check(
    "schema_validation_completeness",
    has_schema,
    "SchemaValidationGovernor with complete audit capability"
    if has_schema else "SchemaValidationGovernor missing or incomplete",
)

# ---- Check 5: Configuration contract fidelity --------------------------------
has_config = (gov is not None
              and hasattr(gov, "ConfigContractFidelityChecker")
              and hasattr(gov, "ConfigDriftDetected"))
if has_config:
    cc = gov.ConfigContractFidelityChecker()
    cc.set_baseline("port", 7000)
    result = cc.check_drift("port", 7000)
    has_config = (
        result["drifted"] is False
        and hasattr(cc, "check_all")
    )
    # Verify drift detection works
    drift_result = cc.check_drift("port", 9999)
    has_config = has_config and drift_result["drifted"] is True
check(
    "config_contract_fidelity",
    has_config,
    "ConfigContractFidelityChecker with baseline + drift detection"
    if has_config else "ConfigContractFidelityChecker missing or incomplete",
)

# ---- Check 6: Dependency lock integrity ---------------------------------------
has_dep = (gov is not None
           and hasattr(gov, "DependencyLockVerifier")
           and hasattr(gov, "DependencyIntegrityError"))
if has_dep:
    dlv = gov.DependencyLockVerifier()
    dlv.load_manifest([
        {"name": "fastapi", "version": "0.116.1"},
        {"name": "pydantic", "version": "2.11.7"},
    ])
    result = dlv.verify()
    has_dep = (
        result["integrity_ok"]
        and result["all_pinned"]
        and result["package_count"] == 2
    )
check(
    "dependency_lock_integrity",
    has_dep,
    "DependencyLockVerifier with pin + hash verification"
    if has_dep else "DependencyLockVerifier missing or incomplete",
)

# ---- Check 7: Release manifest completeness -----------------------------------
has_manifest = (gov is not None
                and hasattr(gov, "ReleaseManifestValidator")
                and hasattr(gov, "REQUIRED_MANIFEST_FIELDS"))
if has_manifest:
    rmv = gov.ReleaseManifestValidator()
    has_manifest = (
        len(gov.REQUIRED_MANIFEST_FIELDS) >= 8
        and hasattr(rmv, "validate")
        and hasattr(rmv, "get_required_fields")
    )
check(
    "release_manifest_completeness",
    has_manifest,
    f"ReleaseManifestValidator with {len(getattr(gov, 'REQUIRED_MANIFEST_FIELDS', set()))} required fields"
    if has_manifest else "ReleaseManifestValidator missing or incomplete",
)

# ---- Check 8: Promotion gate coverage ----------------------------------------
has_promotion = (gov is not None
                 and hasattr(gov, "PromotionGateCoverageChecker")
                 and hasattr(gov, "GateSectionBinding"))
if has_promotion:
    pgc = gov.PromotionGateCoverageChecker()
    pgc.define_sections(["A", "B", "C"])
    pgc.register_gate("gate_1", ["A", "B"])
    pgc.register_gate("gate_2", ["C"])
    result = pgc.check_coverage()
    has_promotion = result["complete"] and result["total_gates"] == 2
check(
    "promotion_gate_coverage",
    has_promotion,
    "PromotionGateCoverageChecker with complete section coverage"
    if has_promotion else "PromotionGateCoverageChecker missing or incomplete",
)

# ---- Check 9: Test strategy compliance ----------------------------------------
has_strategy = (gov is not None
                and hasattr(gov, "TestStrategyComplianceChecker")
                and hasattr(gov, "TestSectionMapping"))
if has_strategy:
    tsc = gov.TestStrategyComplianceChecker()
    tsc.define_required_sections(["A", "B"])
    tsc.register_test("test_a.py", ["A"], has_negative_tests=True)
    tsc.register_test("test_b.py", ["B"], has_negative_tests=True)
    result = tsc.check_compliance()
    has_strategy = (
        result["section_coverage_complete"]
        and result["negative_coverage_complete"]
    )
check(
    "test_strategy_compliance",
    has_strategy,
    "TestStrategyComplianceChecker with section + negative coverage"
    if has_strategy else "TestStrategyComplianceChecker missing or incomplete",
)

# ---- Check 10: Deployment readiness -------------------------------------------
has_deploy = (gov is not None
              and hasattr(gov, "DeploymentReadinessChecker")
              and hasattr(gov, "DeploymentNotReady"))
if has_deploy:
    drc = gov.DeploymentReadinessChecker()
    has_deploy = (
        len(drc.REQUIRED_CHECKS) >= 7
        and hasattr(drc, "record_check")
        and hasattr(drc, "evaluate")
    )
check(
    "deployment_readiness",
    has_deploy,
    f"DeploymentReadinessChecker with {len(getattr(gov.DeploymentReadinessChecker, 'REQUIRED_CHECKS', []))} checks"
    if has_deploy else "DeploymentReadinessChecker missing or incomplete",
)

# ---- Summary -----------------------------------------------------------------
passed = sum(1 for c in checks if c["passed"])
failed = len(checks) - passed

result = {
    "gate": "v40-epic3-gate",
    "version": "4.0.0-dev",
    "epic": "E3: Runtime QoS, Contract Fidelity, Release Discipline",
    "status": "LIVE",
    "checks": checks,
    "passed": passed,
    "failed": failed,
    "total": len(checks),
}

print(f"\n{json.dumps(result, indent=2)}")
print(f"\n{passed}/{len(checks)} checks PASS")

sys.exit(0 if failed == 0 else 1)
