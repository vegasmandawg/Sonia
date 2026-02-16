"""Regression guard: runs all v3.5 baseline gates, fails if any regress."""
import json, os, sys, datetime, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(PYTHON):
    PYTHON = sys.executable

# All v3.5 baseline + v3.6 P1/P2/P3 gates that must remain green
V35_GATES = [
    # v3.5 baseline
    ("secret_scan", os.path.join(ROOT, "scripts", "gates", "secret-scan-gate.py")),
    ("traceability", os.path.join(ROOT, "scripts", "gates", "traceability-gate.py")),
    ("incident_bundle", os.path.join(ROOT, "scripts", "gates", "incident-bundle-gate.py")),
    ("rate_limiter", os.path.join(ROOT, "scripts", "gates", "rate-limiter-gate.py")),
    ("runbook_pragma", os.path.join(ROOT, "scripts", "gates", "_runbook_pragma_gates.py")),
    ("preaudit", os.path.join(ROOT, "scripts", "gates", "consolidated-preaudit.py")),
    ("auth_posture", os.path.join(ROOT, "scripts", "gates", "auth-posture-gate.py")),
    ("unit_test_layer", os.path.join(ROOT, "scripts", "gates", "unit-test-layer-gate.py")),
    ("fallback_behavior", os.path.join(ROOT, "scripts", "gates", "fallback-behavior-gate.py")),
    # v3.6 P1: Security/governance
    ("auth_surface", os.path.join(ROOT, "scripts", "gates", "auth-surface-gate.py")),
    ("policy_enforcement", os.path.join(ROOT, "scripts", "gates", "policy-enforcement-gate.py")),
    # v3.6 P2: Recovery/incident
    ("restore_integrity", os.path.join(ROOT, "scripts", "gates", "restore-integrity-gate.py")),
    ("drill_determinism", os.path.join(ROOT, "scripts", "gates", "drill-determinism-gate.py")),
    ("incident_completeness", os.path.join(ROOT, "scripts", "gates", "incident-completeness-gate.py")),
    # v3.6 P3: Performance/release
    ("perf_budget", os.path.join(ROOT, "scripts", "gates", "perf-budget-gate.py")),
    ("cleanroom_parity", os.path.join(ROOT, "scripts", "gates", "cleanroom-parity-gate.py")),
    ("release_integrity", os.path.join(ROOT, "scripts", "gates", "release-integrity-gate.py")),
]

results = []
for name, path in V35_GATES:
    if not os.path.isfile(path):
        results.append({"gate": name, "passed": False, "detail": f"Script not found: {path}"})
        continue
    try:
        r = subprocess.run([PYTHON, path], capture_output=True, text=True, cwd=ROOT, timeout=180)
        passed = r.returncode == 0
        lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
        summary = lines[-1] if lines else "no output"
        results.append({"gate": name, "passed": passed, "detail": summary})
    except Exception as e:
        results.append({"gate": name, "passed": False, "detail": str(e)})

passed_count = sum(1 for r in results if r["passed"])
total = len(results)
all_pass = passed_count == total

# Any regression = explicit FAIL with detail
regressions = [r for r in results if not r["passed"]]

report = {
    "gate": "regression_guard",
    "timestamp_utc": TS,
    "passed": all_pass,
    "baseline_gates_checked": total,
    "baseline_gates_passed": passed_count,
    "regressions": regressions,
    "results": results,
}

out_dir = os.path.join(ROOT, "reports", "audit")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"regression-guard-{TS}.json")
with open(out, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Regression Guard ({passed_count}/{total}) ===\n")
for r in results:
    s = "PASS" if r["passed"] else "REGRESSION"
    print(f"  [{s}] {r['gate']}")
if regressions:
    print(f"\nREGRESSIONS DETECTED:")
    for r in regressions:
        print(f"  {r['gate']}: {r['detail']}")
print(f"\nArtifact: {out}")
print(f"\n{'PASS' if all_pass else 'FAIL'}")
sys.exit(0 if all_pass else 1)
