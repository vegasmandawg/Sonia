"""v3.7 M2 Gate: Incident Lineage & DLQ Replay Verification.

8 checks validating DLQ replay policy and correlation lineage tracking.
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(r"S:\\")
GW = ROOT / "services" / "api-gateway"

checks = []
def check(name, fn):
    try:
        ok = fn()
        checks.append({"name": name, "result": "PASS" if ok else "FAIL"})
    except Exception as e:
        checks.append({"name": name, "result": "FAIL", "error": str(e)})

# 1. Module exists
def c1():
    return (GW / "dlq_replay_policy.py").exists()
check("dlq_replay_policy_module_exists", c1)

# 2. ReplayDecision enum (3 outcomes)
def c2():
    src = (GW / "dlq_replay_policy.py").read_text()
    return "class ReplayDecision" in src and all(
        d in src for d in ["APPROVE", "REJECT", "DEFER"]
    )
check("replay_decision_enum", c2)

# 3. RejectReason enum (6 reasons)
def c3():
    src = (GW / "dlq_replay_policy.py").read_text()
    return "class RejectReason" in src and all(
        r in src for r in ["ALREADY_REPLAYED", "CIRCUIT_STILL_OPEN",
                           "FAILURE_CLASS_NON_RETRYABLE", "COOLDOWN_ACTIVE",
                           "BUDGET_EXHAUSTED", "MANUAL_BLOCK"]
    )
check("reject_reason_enum", c3)

# 4. NON_RETRYABLE_CLASSES frozenset
def c4():
    src = (GW / "dlq_replay_policy.py").read_text()
    return "NON_RETRYABLE_CLASSES" in src and "frozenset" in src
check("non_retryable_classes_defined", c4)

# 5. CorrelationLineage tracking
def c5():
    src = (GW / "dlq_replay_policy.py").read_text()
    return "class CorrelationLineage" in src and "replay_correlation_ids" in src and "add_replay" in src
check("correlation_lineage_tracking", c5)

# 6. Dry-run isolation (no state mutation)
def c6():
    src = (GW / "dlq_replay_policy.py").read_text()
    return "dry_run" in src and "if not dry_run:" in src
check("dry_run_isolation", c6)

# 7. Replay trace with traceability fields
def c7():
    src = (GW / "dlq_replay_policy.py").read_text()
    return "class ReplayTrace" in src and all(
        f in src for f in ["letter_id", "decision", "original_error_code",
                           "original_failure_class", "correlation_id"]
    )
check("replay_trace_traceability", c7)

# 8. Unit tests exist and pass
def c8():
    test_file = ROOT / "tests" / "unit" / "test_dlq_replay_policy.py"
    if not test_file.exists():
        return False
    import subprocess
    r = subprocess.run(
        [str(ROOT / "envs" / "sonia-core" / "python.exe"), "-m", "pytest", str(test_file), "-q", "--tb=short"],
        capture_output=True, text=True, timeout=60,
    )
    return r.returncode == 0
check("unit_tests_pass", c8)

# Report
ts = time.strftime("%Y%m%d-%H%M%S")
passed = sum(1 for c in checks if c["result"] == "PASS")
total = len(checks)
verdict = "PASS" if passed == total else "FAIL"

report = {"gate": "incident-lineage", "timestamp": ts, "checks": checks, "passed": passed, "total": total, "verdict": verdict}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"incident-lineage-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Incident Lineage Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
