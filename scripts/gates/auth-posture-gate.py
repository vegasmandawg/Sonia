"""Auth posture gate: verifies default-on auth with SONIA_DEV_MODE bypass."""
import json, os, sys, datetime, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: main.py uses SONIA_DEV_MODE, not config "enabled"
main_py = os.path.join(ROOT, "services", "api-gateway", "main.py")
with open(main_py, "r") as f:
    content = f.read()

has_dev_mode_check = 'SONIA_DEV_MODE' in content
has_default_on = 'auth_enabled = not dev_mode' in content
has_warning_log = 'auth_disabled_dev_mode' in content
checks.append({
    "name": "code_default_on",
    "passed": has_dev_mode_check and has_default_on,
    "detail": f"SONIA_DEV_MODE check: {has_dev_mode_check}, default-on logic: {has_default_on}"
})
checks.append({
    "name": "startup_warning",
    "passed": has_warning_log,
    "detail": f"Dev mode warning log event: {has_warning_log}"
})

# Check 3: /status exposes auth_posture
has_posture_exposure = 'auth_posture' in content
checks.append({
    "name": "posture_visibility",
    "passed": has_posture_exposure,
    "detail": f"Status endpoint exposes auth_posture: {has_posture_exposure}"
})

# Check 4: unit tests exist and pass
unit_test = os.path.join(ROOT, "tests", "unit", "test_auth_posture.py")
checks.append({
    "name": "unit_tests_exist",
    "passed": os.path.isfile(unit_test),
    "detail": f"test_auth_posture.py exists: {os.path.isfile(unit_test)}"
})

# Check 5: run unit tests
python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(python):
    python = sys.executable
result = subprocess.run(
    [python, "-m", "pytest", unit_test, "-v", "--tb=short", "-q"],
    capture_output=True, text=True, cwd=ROOT
)
unit_passed = result.returncode == 0
# Parse pass/fail counts
lines = result.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""
checks.append({
    "name": "unit_tests_pass",
    "passed": unit_passed,
    "detail": summary_line,
    "stdout": result.stdout[-500:] if not unit_passed else ""
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "auth_posture",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"auth-posture-gate-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Auth Posture Gate ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")

print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
