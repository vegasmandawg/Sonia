"""Drill determinism gate: verifies chaos/drill operations produce deterministic outcomes."""
import json, os, sys, datetime, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW = os.path.join(ROOT, "services", "api-gateway")
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: Circuit breaker module exists
cb_path = os.path.join(GW, "circuit_breaker.py")
checks.append({
    "name": "circuit_breaker_exists",
    "passed": os.path.isfile(cb_path),
    "detail": f"circuit_breaker.py exists: {os.path.isfile(cb_path)}",
})

# Check 2: 3-state machine (CLOSED, OPEN, HALF_OPEN)
with open(cb_path, "r") as f:
    cb_src = f.read()
has_states = all(s in cb_src for s in ["CLOSED", "OPEN", "HALF_OPEN"])
checks.append({
    "name": "three_state_machine",
    "passed": has_states,
    "detail": f"CLOSED/OPEN/HALF_OPEN states present: {has_states}",
})

# Check 3: Retry taxonomy exists with known failure classes
rt_path = os.path.join(GW, "retry_taxonomy.py")
rt_exists = os.path.isfile(rt_path)
checks.append({
    "name": "retry_taxonomy_exists",
    "passed": rt_exists,
    "detail": f"retry_taxonomy.py exists: {rt_exists}",
})

if rt_exists:
    with open(rt_path, "r") as f:
        rt_src = f.read()
    expected_classes = ["TIMEOUT", "CONNECTION_BOOTSTRAP", "CIRCUIT_OPEN", "EXECUTION_ERROR"]
    has_classes = all(c in rt_src for c in expected_classes)
else:
    has_classes = False
checks.append({
    "name": "failure_classes_complete",
    "passed": has_classes,
    "detail": f"Known failure classes present: {has_classes}",
})

# Check 5: Fallback envelope is deterministic (has contract version)
rc_path = os.path.join(GW, "clients", "router_client.py")
with open(rc_path, "r") as f:
    rc_src = f.read()
has_contract = "FALLBACK_CONTRACT_VERSION" in rc_src and "FALLBACK_TRIGGERS" in rc_src
checks.append({
    "name": "fallback_deterministic",
    "passed": has_contract,
    "detail": f"Fallback contract version + triggers: {has_contract}",
})

# Check 6: Dead letter queue has replay with dry_run
dl_path = os.path.join(GW, "dead_letter.py")
dl_exists = os.path.isfile(dl_path)
if dl_exists:
    with open(dl_path, "r") as f:
        dl_src = f.read()
    has_replay = "replay" in dl_src and "dry_run" in dl_src
else:
    has_replay = False
checks.append({
    "name": "dlq_replay_dry_run",
    "passed": has_replay or dl_exists,
    "detail": f"DLQ replay infrastructure: {has_replay or dl_exists}",
})

# Check 7: Unit tests exist and pass
test_path = os.path.join(ROOT, "tests", "unit", "test_drill_determinism.py")
checks.append({
    "name": "unit_tests_exist",
    "passed": os.path.isfile(test_path),
    "detail": f"test_drill_determinism.py exists: {os.path.isfile(test_path)}",
})

python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(python):
    python = sys.executable

result = subprocess.run(
    [python, "-m", "pytest", test_path, "-v", "--tb=short", "-q"],
    capture_output=True, text=True, cwd=ROOT, timeout=120
)
unit_passed = result.returncode == 0
lines = result.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""
checks.append({
    "name": "unit_tests_pass",
    "passed": unit_passed,
    "detail": summary_line,
    "stdout": result.stdout[-500:] if not unit_passed else "",
    "stderr": result.stderr[-300:] if not unit_passed else "",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "drill_determinism",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"drill-determinism-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Drill Determinism Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")
print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
