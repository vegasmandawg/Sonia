"""Unit-test-layer gate: verifies all policy-critical modules have unit tests."""
import json, os, sys, datetime, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

REQUIRED_MODULES = {
    "rate_limiter": "test_rate_limiter.py",
    "log_redaction": "test_log_redaction.py",
    "tool_policy": "test_tool_policy.py",
    "turn_quality": "test_turn_quality.py",
}
MIN_TESTS_PER_MODULE = 5

checks = []

# Check 1: all test files exist
unit_dir = os.path.join(ROOT, "tests", "unit")
for module, test_file in REQUIRED_MODULES.items():
    path = os.path.join(unit_dir, test_file)
    exists = os.path.isfile(path)
    checks.append({
        "name": f"file_exists:{module}",
        "passed": exists,
        "detail": f"{test_file} exists: {exists}",
    })

# Check 2: run all unit tests and collect counts
python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(python):
    python = sys.executable

result = subprocess.run(
    [python, "-m", "pytest", unit_dir, "-v", "--tb=short", "-q"],
    capture_output=True, text=True, cwd=ROOT
)
all_tests_pass = result.returncode == 0
lines = result.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""

checks.append({
    "name": "all_unit_tests_pass",
    "passed": all_tests_pass,
    "detail": summary_line,
    "stdout": result.stdout[-800:] if not all_tests_pass else "",
})

# Check 3: per-module test count meets minimum
for module, test_file in REQUIRED_MODULES.items():
    path = os.path.join(unit_dir, test_file)
    count_result = subprocess.run(
        [python, "-m", "pytest", path, "--co", "-q"],
        capture_output=True, text=True, cwd=ROOT
    )
    # Count lines that look like test items
    test_lines = [l for l in count_result.stdout.strip().split("\n")
                  if "::" in l and "test_" in l]
    count = len(test_lines)
    meets_min = count >= MIN_TESTS_PER_MODULE
    checks.append({
        "name": f"min_tests:{module}",
        "passed": meets_min,
        "detail": f"{module}: {count} tests (min={MIN_TESTS_PER_MODULE})",
    })

# Check 4: auth posture unit tests also present (M1 artifact)
auth_test = os.path.join(unit_dir, "test_auth_posture.py")
checks.append({
    "name": "auth_posture_tests_exist",
    "passed": os.path.isfile(auth_test),
    "detail": f"test_auth_posture.py exists: {os.path.isfile(auth_test)}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "unit_test_layer",
    "timestamp_utc": TS,
    "passed": all_passed,
    "total_checks": len(checks),
    "checks": checks,
    "modules_covered": list(REQUIRED_MODULES.keys()),
    "min_tests_per_module": MIN_TESTS_PER_MODULE,
}

path = os.path.join(ROOT, "reports", "audit", f"unit-test-layer-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Unit Test Layer Gate ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")

print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
