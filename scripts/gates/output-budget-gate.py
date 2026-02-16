"""v3.7 M3 Gate: Output Budget Enforcement Verification.

8 checks validating deterministic budget enforcement across all output dimensions.
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
    return (GW / "output_budget.py").exists()
check("output_budget_module_exists", c1)

# 2. BudgetDimension enum with 5 dimensions
def c2():
    src = (GW / "output_budget.py").read_text()
    return "class BudgetDimension" in src and all(
        d in src for d in ["OUTPUT_CHARS", "CONTEXT_CHARS", "TOOL_CALLS",
                           "VISION_FRAMES", "MEMORY_ENTRIES"]
    )
check("budget_dimension_enum", c2)

# 3. TruncationStrategy enum with 4 strategies
def c3():
    src = (GW / "output_budget.py").read_text()
    return "class TruncationStrategy" in src and all(
        s in src for s in ["HARD_CUT", "SENTENCE_BOUNDARY", "DROP_OLDEST", "REJECT"]
    )
check("truncation_strategy_enum", c3)

# 4. DEFAULT_BUDGETS configuration
def c4():
    src = (GW / "output_budget.py").read_text()
    return "DEFAULT_BUDGETS" in src and "4000" in src and "7000" in src
check("default_budgets_configured", c4)

# 5. Text enforcement with truncation
def c5():
    src = (GW / "output_budget.py").read_text()
    return "enforce_text" in src and "_truncate_sentence" in src
check("text_enforcement", c5)

# 6. Count enforcement with drop oldest
def c6():
    src = (GW / "output_budget.py").read_text()
    return "enforce_count" in src and "DROP_OLDEST" in src
check("count_enforcement", c6)

# 7. Enforcement log bounded
def c7():
    src = (GW / "output_budget.py").read_text()
    return "get_enforcement_log" in src and "_max_log" in src
check("enforcement_log_bounded", c7)

# 8. Unit tests exist and pass
def c8():
    test_file = ROOT / "tests" / "unit" / "test_output_budget.py"
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

report = {"gate": "output-budget", "timestamp": ts, "checks": checks, "passed": passed, "total": total, "verdict": verdict}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"output-budget-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Output Budget Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
