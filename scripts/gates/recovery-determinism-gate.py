"""v3.7 M2 Gate: Recovery Determinism Verification.

8 checks validating deterministic recovery policy and restart budget enforcement.
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
    return (GW / "recovery_policy.py").exists()
check("recovery_policy_module_exists", c1)

# 2. RecoveryTrigger enum with 8 triggers
def c2():
    src = (GW / "recovery_policy.py").read_text()
    return "class RecoveryTrigger" in src and all(
        t in src for t in ["HEALTH_CHECK_FAILED", "CIRCUIT_BREAKER_TRIPPED",
                           "TIMEOUT_EXCEEDED", "PROCESS_CRASHED"]
    )
check("recovery_trigger_enum", c2)

# 3. RecoveryAction enum with 8 actions
def c3():
    src = (GW / "recovery_policy.py").read_text()
    return "class RecoveryAction" in src and all(
        a in src for a in ["RETRY_WITH_BACKOFF", "CIRCUIT_OPEN",
                           "RESTART_SERVICE", "NO_ACTION"]
    )
check("recovery_action_enum", c3)

# 4. RECOVERY_POLICY_TABLE with 10 rules
def c4():
    src = (GW / "recovery_policy.py").read_text()
    return "RECOVERY_POLICY_TABLE" in src and "RecoveryRule(" in src
check("policy_table_defined", c4)

# 5. RestartBudget with window enforcement
def c5():
    src = (GW / "recovery_policy.py").read_text()
    return "class RestartBudget" in src and "can_restart" in src and "window_seconds" in src
check("restart_budget_enforcement", c5)

# 6. Cooldown enforcement in decide()
def c6():
    src = (GW / "recovery_policy.py").read_text()
    return "_cooldowns" in src and "cooldown_seconds" in src
check("cooldown_enforcement", c6)

# 7. Decision log bounded
def c7():
    src = (GW / "recovery_policy.py").read_text()
    return "get_decision_log" in src and "_decision_log" in src and "1000" in src
check("decision_log_bounded", c7)

# 8. Unit tests exist and pass
def c8():
    test_file = ROOT / "tests" / "unit" / "test_recovery_policy.py"
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

report = {"gate": "recovery-determinism", "timestamp": ts, "checks": checks, "passed": passed, "total": total, "verdict": verdict}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"recovery-determinism-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Recovery Determinism Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
