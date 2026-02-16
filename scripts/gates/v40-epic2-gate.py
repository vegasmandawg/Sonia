"""
v4.0 Epic 2 Gate -- Recovery, Incident Lineage, Determinism
============================================================
10 concrete checks validating E2 modules exist and pass structural invariants.

Exit 0 = PASS, exit 1 = FAIL.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path("S:/")
GATEWAY = REPO_ROOT / "services" / "api-gateway"
TESTS_UNIT = REPO_ROOT / "tests" / "unit"

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


# ---- Load E2 governance module ------------------------------------------------
print("=== v4.0 Epic 2 Gate: Recovery, Incident Lineage, Determinism ===\n")

gov_path = GATEWAY / "recovery_governance.py"
gov = load_module("recovery_governance", gov_path)

# ---- Check 1: Restore preconditions ------------------------------------------
has_precond = (gov is not None
               and hasattr(gov, "RestorePreconditionChecker")
               and hasattr(gov, "RestorePreconditionFailure"))
if has_precond:
    checker = gov.RestorePreconditionChecker()
    has_precond = (
        hasattr(checker, "record_check")
        and hasattr(checker, "evaluate")
        and len(checker.REQUIRED_CHECKS) >= 5
    )
check(
    "restore_preconditions",
    has_precond,
    f"RestorePreconditionChecker with {len(getattr(gov.RestorePreconditionChecker, 'REQUIRED_CHECKS', set()))} checks"
    if has_precond else "RestorePreconditionChecker missing or incomplete",
)

# ---- Check 2: Post-restore verification --------------------------------------
has_postverify = (gov is not None
                  and hasattr(gov, "PostRestoreVerifier")
                  and hasattr(gov, "RestoreVerificationResult"))
if has_postverify:
    verifier = gov.PostRestoreVerifier()
    has_postverify = (
        hasattr(verifier, "check_invariant")
        and hasattr(verifier, "verify")
        and len(verifier.INVARIANTS) >= 5
    )
check(
    "post_restore_verification",
    has_postverify,
    f"PostRestoreVerifier with {len(getattr(gov.PostRestoreVerifier, 'INVARIANTS', []))} invariants"
    if has_postverify else "PostRestoreVerifier missing or incomplete",
)

# ---- Check 3: DLQ dry-run/real-run divergence controls -----------------------
has_divergence = (gov is not None
                  and hasattr(gov, "DLQDivergenceGuard")
                  and hasattr(gov, "DLQDivergenceError"))
if has_divergence:
    guard = gov.DLQDivergenceGuard()
    has_divergence = (
        hasattr(guard, "record_dry_run")
        and hasattr(guard, "validate_real_run")
        and hasattr(guard, "get_stats")
    )
check(
    "dlq_divergence_controls",
    has_divergence,
    "DLQDivergenceGuard with dry/real validation" if has_divergence
    else "DLQDivergenceGuard missing or incomplete",
)

# ---- Check 4: Breaker state transitions deterministic ------------------------
has_breaker = (gov is not None
               and hasattr(gov, "BreakerTransitionValidator")
               and hasattr(gov, "BreakerTransitionError"))
if has_breaker:
    validator = gov.BreakerTransitionValidator()
    has_breaker = (
        validator.is_matrix_complete()
        and len(validator.ALL_STATES) == 3
        and hasattr(validator, "validate_transition")
    )
check(
    "breaker_transitions_deterministic",
    has_breaker,
    f"BreakerTransitionValidator with complete {len(getattr(gov.BreakerTransitionValidator, 'ALL_STATES', set()))}-state matrix"
    if has_breaker else "BreakerTransitionValidator missing or incomplete",
)

# ---- Check 5: Retry taxonomy completeness ------------------------------------
has_taxonomy = (gov is not None
                and hasattr(gov, "RetryTaxonomyAuditor"))
if has_taxonomy:
    # Also verify the actual retry_taxonomy.py module is complete
    tax_mod = load_module("retry_taxonomy", GATEWAY / "retry_taxonomy.py")
    if tax_mod and hasattr(tax_mod, "FailureClass") and hasattr(tax_mod, "RETRY_POLICY"):
        auditor = gov.RetryTaxonomyAuditor()
        fc_values = [fc.value for fc in tax_mod.FailureClass]
        # Convert enum keys to string values for audit
        policy_by_value = {}
        for k, v in tax_mod.RETRY_POLICY.items():
            key = k.value if hasattr(k, "value") else str(k)
            policy_by_value[key] = v
        result = auditor.audit(fc_values, policy_by_value)
        has_taxonomy = result["complete"]
    else:
        has_taxonomy = False
check(
    "retry_taxonomy_completeness",
    has_taxonomy,
    "RetryTaxonomyAuditor: all FailureClass entries have valid policies"
    if has_taxonomy else "Retry taxonomy incomplete",
)

# ---- Check 6: Fallback contract consistency ----------------------------------
has_fallback = (gov is not None
                and hasattr(gov, "FallbackContractVerifier")
                and hasattr(gov, "FallbackPath"))
if has_fallback:
    verifier = gov.FallbackContractVerifier()
    # Register standard fallback contracts
    verifier.register_fallback("restart_service", "dlq_enqueue")
    verifier.register_fallback("circuit_open", "retry_with_backoff")
    verifier.register_fallback("failover_to_fallback", "dlq_enqueue")
    # Verify with real recovery policy table
    rpol = load_module("recovery_policy", GATEWAY / "recovery_policy.py")
    if rpol and hasattr(rpol, "RECOVERY_POLICY_TABLE"):
        rules = [r.to_dict() for r in rpol.RECOVERY_POLICY_TABLE]
        result = verifier.verify_contracts(rules)
        has_fallback = result["consistent"]
    else:
        has_fallback = False
check(
    "fallback_contract_consistency",
    has_fallback,
    "FallbackContractVerifier: all fallback paths consistent"
    if has_fallback else "Fallback contracts inconsistent",
)

# ---- Check 7: Incident bundle artifact completeness -------------------------
has_incident = (gov is not None
                and hasattr(gov, "IncidentBundleValidator")
                and hasattr(gov, "IncidentBundleSpec"))
if has_incident:
    validator = gov.IncidentBundleValidator()
    has_incident = (
        len(validator.REQUIRED_FIELDS) >= 8
        and hasattr(validator, "validate")
        and hasattr(validator, "validate_spec")
    )
check(
    "incident_bundle_completeness",
    has_incident,
    f"IncidentBundleValidator with {len(getattr(gov.IncidentBundleValidator, 'REQUIRED_FIELDS', set()))} required fields"
    if has_incident else "IncidentBundleValidator missing or incomplete",
)

# ---- Check 8: Correlation lineage continuity ---------------------------------
has_lineage = (gov is not None
               and hasattr(gov, "CorrelationLineageTracker")
               and hasattr(gov, "LineageNode"))
if has_lineage:
    tracker = gov.CorrelationLineageTracker()
    required_methods = {"record_event", "get_chain", "check_continuity", "find_orphans"}
    has_lineage = required_methods.issubset(set(dir(tracker)))
    if has_lineage:
        # Verify deterministic chain construction
        tracker.record_event("c1", None, "original")
        tracker.record_event("c2", "c1", "retry")
        chain = tracker.get_chain("c2")
        has_lineage = len(chain) == 2 and chain[0]["correlation_id"] == "c1"
check(
    "correlation_lineage_continuity",
    has_lineage,
    "CorrelationLineageTracker with verified chain construction"
    if has_lineage else "CorrelationLineageTracker missing or incomplete",
)

# ---- Check 9: Rollback script readiness --------------------------------------
has_rollback = (gov is not None
                and hasattr(gov, "RollbackReadinessChecker")
                and hasattr(gov, "RollbackNotReady"))
if has_rollback:
    checker = gov.RollbackReadinessChecker()
    has_rollback = (
        len(checker.REQUIRED_CHECKS) >= 5
        and hasattr(checker, "record_check")
        and hasattr(checker, "evaluate")
    )
check(
    "rollback_script_readiness",
    has_rollback,
    f"RollbackReadinessChecker with {len(getattr(gov.RollbackReadinessChecker, 'REQUIRED_CHECKS', []))} checks"
    if has_rollback else "RollbackReadinessChecker missing or incomplete",
)

# ---- Check 10: Reproducibility hash stability --------------------------------
has_repro = (gov is not None
             and hasattr(gov, "RecoveryReproducibilityHasher"))
if has_repro:
    hasher = gov.RecoveryReproducibilityHasher()
    # Set a policy hash first
    hasher.set_policy_hash([{"test": "rule"}])
    # Verify deterministic: same input -> same hash
    h1 = hasher.hash_decision("svc", "healthy", "timeout", "req_1", "retry")
    h2 = hasher.hash_decision("svc", "healthy", "timeout", "req_1", "retry")
    h3 = hasher.hash_decision("svc", "healthy", "timeout", "req_2", "retry")
    has_repro = (h1 == h2 and h1 != h3 and len(h1) == 64)
check(
    "reproducibility_hash_stability",
    has_repro,
    "RecoveryReproducibilityHasher with deterministic verification"
    if has_repro else "RecoveryReproducibilityHasher missing or non-deterministic",
)

# ---- Summary -----------------------------------------------------------------
passed = sum(1 for c in checks if c["passed"])
failed = len(checks) - passed

result = {
    "gate": "v40-epic2-gate",
    "version": "4.0.0-dev",
    "epic": "E2: Recovery, Incident Lineage, Determinism",
    "status": "LIVE",
    "checks": checks,
    "passed": passed,
    "failed": failed,
    "total": len(checks),
}

print(f"\n{json.dumps(result, indent=2)}")
print(f"\n{passed}/{len(checks)} checks PASS")

sys.exit(0 if failed == 0 else 1)
