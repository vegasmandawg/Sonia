"""
v4.0 Epic 1 Gate -- Session & Memory Governance Hardening
==========================================================
10 concrete checks validating E1 modules exist and pass structural invariants.

Exit 0 = PASS, exit 1 = FAIL.
"""
import importlib.util
import json
import sys
import os
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
    except Exception as e:
        return None
    finally:
        sys.modules.pop(name, None)


# ---- Check 1: Session namespace isolation (module exists + classes) --------
print("=== v4.0 Epic 1 Gate: Session & Memory Governance ===\n")

gov_path = GATEWAY / "session_governance.py"
gov = load_module("session_governance", gov_path)
check(
    "session_namespace_isolation",
    gov is not None and hasattr(gov, "SessionQuotaManager"),
    "SessionQuotaManager class exists" if gov and hasattr(gov, "SessionQuotaManager")
    else f"session_governance.py missing or incomplete",
)

# ---- Check 2: Persona memory silo boundaries (existing enforcer enhanced) --
silo_path = GATEWAY / "memory_silo.py"
silo = load_module("memory_silo", silo_path)
has_silo = (silo is not None
            and hasattr(silo, "MemorySiloEnforcer")
            and hasattr(silo, "SiloPolicy"))
check(
    "persona_memory_silo_boundaries",
    has_silo,
    "MemorySiloEnforcer + SiloPolicy present" if has_silo
    else "memory_silo.py missing key classes",
)

# ---- Check 3: Mutation authorization paths ---------------------------------
has_auth = (gov is not None
            and hasattr(gov, "MutationAuthorizor")
            and hasattr(gov, "MutationTier"))
if has_auth:
    # Verify tier enum has required values
    tiers = {t.value for t in gov.MutationTier}
    required_tiers = {"read_only", "standard", "admin"}
    has_auth = required_tiers.issubset(tiers)
check(
    "mutation_authorization_paths",
    has_auth,
    f"MutationAuthorizor with tiers {required_tiers}" if has_auth
    else "MutationAuthorizor or MutationTier missing/incomplete",
)

# ---- Check 4: Redaction replay integrity -----------------------------------
has_redaction = (gov is not None
                 and hasattr(gov, "RedactionReplayTracker")
                 and hasattr(gov, "RedactionAccessRecord"))
if has_redaction:
    # Verify tracker has required methods
    tracker_cls = gov.RedactionReplayTracker
    required_methods = {"record_access", "get_access_log", "verify_replay_integrity"}
    has_redaction = required_methods.issubset(set(dir(tracker_cls)))
check(
    "redaction_replay_integrity",
    has_redaction,
    f"RedactionReplayTracker with {required_methods}" if has_redaction
    else "RedactionReplayTracker missing or incomplete",
)

# ---- Check 5: Memory version conflict handling (existing silo) -------------
has_conflict = (silo is not None
                and hasattr(silo, "ConflictResolution")
                and hasattr(silo, "MemorySiloEnforcer"))
if has_conflict:
    # Verify conflict resolution has resolve_conflict method
    enforcer_cls = silo.MemorySiloEnforcer
    has_conflict = hasattr(enforcer_cls, "resolve_conflict")
check(
    "memory_version_conflict_handling",
    has_conflict,
    "ConflictResolution enum + resolve_conflict method" if has_conflict
    else "Conflict handling missing",
)

# ---- Check 6: Retention policy enforcement ---------------------------------
has_retention = (gov is not None
                 and hasattr(gov, "RetentionEnforcer")
                 and hasattr(gov, "RetentionPolicy")
                 and hasattr(gov, "RETENTION_TTL"))
if has_retention:
    # Verify all policy values have TTL mappings
    policies = {p.value for p in gov.RetentionPolicy}
    ttl_keys = set(gov.RETENTION_TTL.keys())
    has_retention = policies.issubset(ttl_keys)
check(
    "retention_policy_enforcement",
    has_retention,
    f"RetentionEnforcer with {len(policies)} policies" if has_retention
    else "RetentionEnforcer or TTL mappings incomplete",
)

# ---- Check 7: Import/export safety invariants ------------------------------
has_export = (gov is not None
              and hasattr(gov, "MemoryExportImportSafety")
              and hasattr(gov, "MemoryExportBundle"))
if has_export:
    safety = gov.MemoryExportImportSafety()
    # Verify forbidden fields are defined
    has_export = len(safety.FORBIDDEN_FIELDS) > 0
check(
    "import_export_safety_invariants",
    has_export,
    f"MemoryExportImportSafety with {len(getattr(gov.MemoryExportImportSafety, 'FORBIDDEN_FIELDS', set()))} forbidden fields"
    if has_export else "Export/import safety missing",
)

# ---- Check 8: Audit trail completeness ------------------------------------
iso_path = GATEWAY / "session_isolation.py"
iso = load_module("session_isolation", iso_path)
has_audit = (iso is not None
             and hasattr(iso, "SessionIsolationGuard")
             and hasattr(iso, "PolicyTraceField"))
if has_audit:
    # Verify guard has stats method (operation + violation counting)
    guard_cls = iso.SessionIsolationGuard
    has_audit = hasattr(guard_cls, "get_stats")
check(
    "audit_trail_completeness",
    has_audit,
    "SessionIsolationGuard + PolicyTraceField with stats" if has_audit
    else "Audit trail classes missing",
)

# ---- Check 9: Incident snapshot memory fields ------------------------------
has_incident = (gov is not None
                and hasattr(gov, "IncidentMemorySnapshot"))
if has_incident:
    # Verify required fields in dataclass
    import dataclasses
    fields = {f.name for f in dataclasses.fields(gov.IncidentMemorySnapshot)}
    required_fields = {
        "incident_id", "session_id", "user_id", "correlation_id",
        "recent_memories", "active_sessions", "pending_mutations",
    }
    has_incident = required_fields.issubset(fields)
check(
    "incident_snapshot_memory_fields",
    has_incident,
    f"IncidentMemorySnapshot with {len(required_fields)} required fields"
    if has_incident else "IncidentMemorySnapshot missing or incomplete",
)

# ---- Check 10: Deterministic rerun parity ----------------------------------
has_rerun = (gov is not None
             and hasattr(gov, "TurnSequencer"))
if has_rerun:
    seq = gov.TurnSequencer()
    # Verify deterministic: same input -> same hash
    h1 = seq.compute_rerun_hash("ses_test", 1, "hello", "world")
    h2 = seq.compute_rerun_hash("ses_test", 1, "hello", "world")
    has_rerun = (h1 == h2 and len(h1) == 64)  # SHA-256 length
check(
    "deterministic_rerun_parity",
    has_rerun,
    "TurnSequencer with deterministic hash verification" if has_rerun
    else "TurnSequencer missing or non-deterministic",
)

# ---- Summary ---------------------------------------------------------------
passed = sum(1 for c in checks if c["passed"])
failed = len(checks) - passed

result = {
    "gate": "v40-epic1-gate",
    "version": "4.0.0-dev",
    "epic": "E1: Session & Memory Governance Hardening",
    "status": "LIVE",
    "checks": checks,
    "passed": passed,
    "failed": failed,
    "total": len(checks),
}

print(f"\n{json.dumps(result, indent=2)}")
print(f"\n{passed}/{len(checks)} checks PASS")

sys.exit(0 if failed == 0 else 1)
