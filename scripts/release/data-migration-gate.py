#!/usr/bin/env python3
"""
Data Migration Gate — Epic 1 delta gate.

Checks (≥8 required):
1. MigrationPolicyEngine importable
2. Linear dependency chain validates correctly
3. Cycle detection works
4. Missing dependency detection works
5. Idempotent skip decision correct
6. Non-idempotent block decision correct
7. Dependency-order blocking works
8. Pending list respects topological order
9. CodeQualityChecker importable and functional
10. CodeQualityChecker detects bare except + print calls
"""
from __future__ import annotations

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\memory-engine")
sys.path.insert(0, r"S:\services\api-gateway")

CHECKS: list[dict] = []


def check(name: str, passed: bool, detail: str = ""):
    CHECKS.append({"name": name, "passed": passed, "detail": detail})


def main():
    # --- MigrationPolicyEngine checks ---
    try:
        from migration_policy import Migration, MigrationPolicyEngine, RollbackStrategy
        check("migration_engine_importable", True)
    except Exception as e:
        check("migration_engine_importable", False, str(e))
        return report()

    # Check 2: linear chain validates
    engine = MigrationPolicyEngine()
    engine.register(Migration(version="v1", description="init"))
    engine.register(Migration(version="v2", description="idx", depends_on=["v1"]))
    engine.register(Migration(version="v3", description="col", depends_on=["v2"]))
    graph = engine.validate_graph()
    check("linear_chain_valid", graph.valid and graph.total_migrations == 3,
          f"valid={graph.valid}, total={graph.total_migrations}")

    # Check 3: cycle detection
    cyc_engine = MigrationPolicyEngine()
    cyc_engine.register(Migration(version="a", description="A", depends_on=["b"]))
    cyc_engine.register(Migration(version="b", description="B", depends_on=["a"]))
    cyc_result = cyc_engine.validate_graph()
    check("cycle_detected", not cyc_result.valid and len(cyc_result.cycles) > 0,
          f"valid={cyc_result.valid}, cycles={cyc_result.cycles}")

    # Check 4: missing dependency
    miss_engine = MigrationPolicyEngine()
    miss_engine.register(Migration(version="v1", description="t", depends_on=["v0"]))
    miss_result = miss_engine.validate_graph()
    check("missing_dep_detected", not miss_result.valid and len(miss_result.missing_deps) > 0,
          f"missing={miss_result.missing_deps}")

    # Check 5: idempotent skip
    engine.mark_applied("v1")
    decision = engine.decide("v1")
    check("idempotent_skip", decision.action == "skip", f"action={decision.action}")

    # Check 6: non-idempotent block
    ni_engine = MigrationPolicyEngine()
    ni_engine.register(Migration(version="x1", description="t", idempotent=False))
    ni_engine.mark_applied("x1")
    ni_decision = ni_engine.decide("x1")
    check("non_idempotent_block", ni_decision.action == "block", f"action={ni_decision.action}")

    # Check 7: dependency blocking
    dep_decision = engine.decide("v3")  # v2 not applied
    check("dependency_blocking", dep_decision.action == "block", f"action={dep_decision.action}")

    # Check 8: pending respects order
    fresh = MigrationPolicyEngine()
    fresh.register(Migration(version="v1", description="init"))
    fresh.register(Migration(version="v2", description="idx", depends_on=["v1"]))
    fresh.register(Migration(version="v3", description="col", depends_on=["v2"]))
    pending = fresh.get_pending()
    check("pending_order", len(pending) == 3 and pending.index("v1") < pending.index("v2") < pending.index("v3"),
          f"pending={pending}")

    # --- CodeQualityChecker checks ---
    try:
        from code_quality import CodeQualityChecker
        check("code_quality_importable", True)
    except Exception as e:
        check("code_quality_importable", False, str(e))
        return report()

    # Check 10: detects bare except + print
    src = '''
def bad_func():
    """Bad function."""
    try:
        pass
    except:
        print("error")
'''
    tmpfile = Path(tempfile.mktemp(suffix=".py"))
    tmpfile.write_text(src, encoding="utf-8")
    checker = CodeQualityChecker()
    violations = checker.check_file(tmpfile)
    has_bare = any(v.rule == "bare_except" for v in violations)
    has_print = any(v.rule == "print_in_production" for v in violations)
    check("quality_detects_violations", has_bare and has_print,
          f"bare_except={has_bare}, print={has_print}")
    tmpfile.unlink(missing_ok=True)

    return report()


def report():
    passed = sum(1 for c in CHECKS if c["passed"])
    total = len(CHECKS)
    verdict = "PASS" if passed >= 8 and all(c["passed"] for c in CHECKS) else "FAIL"

    print(f"\n=== Data Migration Gate ===")
    for c in CHECKS:
        status = "PASS" if c["passed"] else "FAIL"
        detail = f" ({c['detail']})" if c["detail"] else ""
        print(f"  [{status}] {c['name']}{detail}")
    print(f"\nResult: {passed}/{total} checks passed — {verdict}")

    # Write JSON artifact
    artifact = {
        "gate": "data-migration-gate",
        "checks": CHECKS,
        "passed": passed,
        "total": total,
        "verdict": verdict,
    }
    artifact_dir = Path(r"S:\reports\audit")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = artifact_dir / f"data-migration-gate-{ts}.json"
    with open(artifact_path, "w") as f:
        json.dump(artifact, f, indent=2)
    print(f"Artifact: {artifact_path}")

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
