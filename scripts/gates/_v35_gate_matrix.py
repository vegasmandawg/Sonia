"""v3.5 gate matrix: runs baseline + 3 new gates, emits single consolidated artifact."""
import json, os, sys, datetime, subprocess, hashlib

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(PYTHON):
    PYTHON = sys.executable

GATES = [
    # Baseline gates
    ("secret_scan", os.path.join(ROOT, "scripts", "gates", "secret-scan-gate.py")),
    ("traceability", os.path.join(ROOT, "scripts", "gates", "traceability-gate.py")),
    ("incident_bundle", os.path.join(ROOT, "scripts", "gates", "incident-bundle-gate.py")),
    ("rate_limiter", os.path.join(ROOT, "scripts", "gates", "rate-limiter-gate.py")),
    ("runbook_pragma", os.path.join(ROOT, "scripts", "gates", "_runbook_pragma_gates.py")),
    ("preaudit", os.path.join(ROOT, "scripts", "gates", "consolidated-preaudit.py")),
    # v3.5 new gates
    ("auth_posture", os.path.join(ROOT, "scripts", "gates", "auth-posture-gate.py")),
    ("unit_test_layer", os.path.join(ROOT, "scripts", "gates", "unit-test-layer-gate.py")),
    ("fallback_behavior", os.path.join(ROOT, "scripts", "gates", "fallback-behavior-gate.py")),
]

results = []
for name, path in GATES:
    if not os.path.isfile(path):
        results.append({"gate": name, "passed": False, "detail": f"Script not found: {path}"})
        continue
    try:
        r = subprocess.run(
            [PYTHON, path],
            capture_output=True, text=True, cwd=ROOT, timeout=180
        )
        passed = r.returncode == 0
        # Extract summary from last non-empty line
        lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
        summary = lines[-1] if lines else "no output"
        results.append({"gate": name, "passed": passed, "detail": summary, "returncode": r.returncode})
    except Exception as e:
        results.append({"gate": name, "passed": False, "detail": str(e)})

gates_passed = sum(1 for r in results if r["passed"])
gates_total = len(results)
all_pass = gates_passed == gates_total

report = {
    "matrix": "v3.5_gate_sweep",
    "timestamp_utc": TS,
    "gates_passed": gates_passed,
    "gates_total": gates_total,
    "all_pass": all_pass,
    "verdict": "PROMOTE" if all_pass else "BLOCK",
    "results": results,
}

out_dir = os.path.join(ROOT, "reports", "audit")
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, f"v35-gate-matrix-{TS}.json")
with open(out_path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== v3.5 Gate Matrix ({gates_passed}/{gates_total}) ===\n")
for r in results:
    status = "PASS" if r["passed"] else "FAIL"
    print(f"  [{status}] {r['gate']}")
print(f"\nVerdict: {report['verdict']}")
print(f"Artifact: {out_path}")
sys.exit(0 if all_pass else 1)
