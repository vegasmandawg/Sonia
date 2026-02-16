"""v3.7 M3 Gate: Runtime QoS Engine Verification.

8 checks validating SLO monitoring, latency tracking, and turn annotations.
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
    return (GW / "runtime_qos.py").exists()
check("runtime_qos_module_exists", c1)

# 2. SLOTier enum with 4 tiers
def c2():
    src = (GW / "runtime_qos.py").read_text()
    return "class SLOTier" in src and all(
        t in src for t in ["INTERACTIVE", "STANDARD", "BATCH", "BACKGROUND"]
    )
check("slo_tier_enum", c2)

# 3. DEFAULT_SLO_TARGETS with p50/p95/p99
def c3():
    src = (GW / "runtime_qos.py").read_text()
    return "DEFAULT_SLO_TARGETS" in src and all(
        f in src for f in ["p50_ms", "p95_ms", "p99_ms"]
    )
check("default_slo_targets", c3)

# 4. QoSViolationType enum
def c4():
    src = (GW / "runtime_qos.py").read_text()
    return "class QoSViolationType" in src and all(
        v in src for v in ["LATENCY_EXCEEDED", "TIMEOUT", "BUDGET_EXCEEDED"]
    )
check("violation_type_enum", c4)

# 5. TurnQoSAnnotation with deterministic fields
def c5():
    src = (GW / "runtime_qos.py").read_text()
    return "class TurnQoSAnnotation" in src and "slo_met" in src and "latency_breakdown" in src
check("turn_annotation_dataclass", c5)

# 6. Percentile calculation
def c6():
    src = (GW / "runtime_qos.py").read_text()
    return "get_percentiles" in src and "p50" in src and "p95" in src
check("percentile_calculation", c6)

# 7. Violation log bounded
def c7():
    src = (GW / "runtime_qos.py").read_text()
    return "get_violations" in src and "_max_violations" in src
check("violation_log_bounded", c7)

# 8. Unit tests exist and pass
def c8():
    test_file = ROOT / "tests" / "unit" / "test_runtime_qos.py"
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

report = {"gate": "runtime-qos", "timestamp": ts, "checks": checks, "passed": passed, "total": total, "verdict": verdict}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"runtime-qos-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Runtime QoS Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
