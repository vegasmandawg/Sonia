"""v3.7 M1 Gate: Memory Silo Enforcement Verification.

8 checks validating persona-siloed memory access and conflict resolution.
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
    return (GW / "memory_silo.py").exists()
check("memory_silo_module_exists", c1)

# 2. SiloPolicy with persona_id
def c2():
    src = (GW / "memory_silo.py").read_text()
    return "class SiloPolicy" in src and "persona_id" in src
check("silo_policy_dataclass", c2)

# 3. ConflictResolution enum with all 4 strategies
def c3():
    src = (GW / "memory_silo.py").read_text()
    return all(s in src for s in ["LAST_WRITE_WINS", "FIRST_WRITE_WINS", "HIGHER_PRIORITY_WINS", "MANUAL_REVIEW"])
check("conflict_resolution_strategies", c3)

# 4. Memory type priority ordering
def c4():
    src = (GW / "memory_silo.py").read_text()
    return "MEMORY_TYPE_PRIORITY" in src and "correction" in src
check("memory_type_priority", c4)

# 5. Cross-persona read enforcement
def c5():
    src = (GW / "memory_silo.py").read_text()
    return "enforce_read" in src and "Cross-persona read blocked" in src
check("cross_persona_read_enforcement", c5)

# 6. Write type enforcement
def c6():
    src = (GW / "memory_silo.py").read_text()
    return "enforce_write" in src and "allows_write_type" in src
check("write_type_enforcement", c6)

# 7. Immutable ledger with bounded growth
def c7():
    src = (GW / "memory_silo.py").read_text()
    return "class LedgerEntry" in src and "_max_ledger" in src and "get_ledger" in src
check("immutable_bounded_ledger", c7)

# 8. Unit tests exist and pass
def c8():
    test_file = ROOT / "tests" / "unit" / "test_memory_silo_enforcement.py"
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

report = {"gate": "memory-silo", "timestamp": ts, "checks": checks, "passed": passed, "total": total, "verdict": verdict}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"memory-silo-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Memory Silo Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
