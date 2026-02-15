"""Fallback behavior gate: verifies codified automatic fallback in router_client."""
import json, os, sys, datetime, subprocess, ast

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# Check 1: chat_with_fallback method exists in router_client.py
rc_path = os.path.join(ROOT, "services", "api-gateway", "clients", "router_client.py")
with open(rc_path, "r") as f:
    content = f.read()

has_method = "async def chat_with_fallback" in content
checks.append({
    "name": "method_exists",
    "passed": has_method,
    "detail": f"chat_with_fallback method in router_client.py: {has_method}",
})

# Check 2: fallback returns deterministic response (not raises)
has_fallback_return = "fallback_used" in content and '"fallback"' in content
checks.append({
    "name": "deterministic_fallback",
    "passed": has_fallback_return,
    "detail": f"Deterministic fallback response (fallback_used + model=fallback): {has_fallback_return}",
})

# Check 3: fallback preserves correlation_id
has_corr_preserve = "correlation_id" in content.split("chat_with_fallback")[1] if has_method else False
checks.append({
    "name": "correlation_preserved",
    "passed": has_corr_preserve,
    "detail": f"Correlation ID preserved in fallback path: {has_corr_preserve}",
})

# Check 4: unit tests exist
test_path = os.path.join(ROOT, "tests", "unit", "test_fallback_behavior.py")
checks.append({
    "name": "unit_tests_exist",
    "passed": os.path.isfile(test_path),
    "detail": f"test_fallback_behavior.py exists: {os.path.isfile(test_path)}",
})

# Check 5: unit tests pass
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
})

# Check 6: exception handler catches both RouterClientError and generic Exception
has_broad_catch = "except (RouterClientError, Exception)" in content or "except Exception" in content
checks.append({
    "name": "broad_exception_handling",
    "passed": has_broad_catch,
    "detail": f"Catches RouterClientError + generic exceptions: {has_broad_catch}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "fallback_behavior",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"fallback-behavior-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Fallback Behavior Gate ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")

print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
