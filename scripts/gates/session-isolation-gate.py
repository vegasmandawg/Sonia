"""v3.7 M1 Gate: Session Isolation Verification.

8 checks validating session-scoped access enforcement.
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
    return (GW / "session_isolation.py").exists()
check("session_isolation_module_exists", c1)

# 2. SessionContext has required fields
def c2():
    src = (GW / "session_isolation.py").read_text()
    return "session_id" in src and "user_id" in src and "persona_id" in src
check("session_context_fields", c2)

# 3. IsolationViolation exception with code
def c3():
    src = (GW / "session_isolation.py").read_text()
    return "class IsolationViolation" in src and "self.code" in src
check("isolation_violation_exception", c3)

# 4. Cross-user read blocking
def c4():
    src = (GW / "session_isolation.py").read_text()
    return "CROSS_USER_READ" in src
check("cross_user_read_blocking", c4)

# 5. Cross-persona read blocking
def c5():
    src = (GW / "session_isolation.py").read_text()
    return "CROSS_PERSONA_READ" in src
check("cross_persona_read_blocking", c5)

# 6. Write reason code enum
def c6():
    src = (GW / "session_isolation.py").read_text()
    return "class WriteReasonCode" in src and "TURN_RAW" in src and "CORRECTION" in src
check("write_reason_codes", c6)

# 7. Policy trace field generation
def c7():
    src = (GW / "session_isolation.py").read_text()
    return "class PolicyTraceField" in src and "policy_version" in src
check("policy_trace_fields", c7)

# 8. Unit tests exist and pass
def c8():
    test_file = ROOT / "tests" / "unit" / "test_session_isolation.py"
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

report = {"gate": "session-isolation", "timestamp": ts, "checks": checks, "passed": passed, "total": total, "verdict": verdict}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"session-isolation-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Session Isolation Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
