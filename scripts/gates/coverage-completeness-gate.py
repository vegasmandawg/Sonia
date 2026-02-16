"""
Coverage Completeness Gate (10 checks)
======================================
Verifies every scorer section maps to at least one gate, test family,
and artifact pattern. Focuses on Epic 1 target sections (J,S,M,O,Q,W).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(r"S:\\")
sys.path.insert(0, str(ROOT / "services" / "api-gateway"))

checks = []


def check(name, fn):
    try:
        ok = fn()
        checks.append({"name": name, "result": "PASS" if ok else "FAIL"})
    except Exception as e:
        checks.append({"name": name, "result": "FAIL", "error": str(e)})


# 1. Coverage completeness module importable
def c1():
    import coverage_completeness
    return hasattr(coverage_completeness, "CoverageCompletenessAnalyzer")
check("module_importable", c1)


# 2. Section registry has all 25 sections (A-Y)
def c2():
    from coverage_completeness import SECTION_NAMES
    expected = set("ABCDEFGHIJKLMNOPQRSTUVWXY")
    return set(SECTION_NAMES.keys()) == expected
check("section_registry_complete", c2)


# 3. Gate map covers at least 20 sections
def c3():
    from coverage_completeness import GATE_SECTION_MAP
    covered = set()
    for sections in GATE_SECTION_MAP.values():
        covered.update(sections)
    return len(covered) >= 20
check("gate_map_breadth", c3)


# 4. Test map covers at least 20 sections
def c4():
    from coverage_completeness import TEST_SECTION_MAP
    covered = set()
    for sections in TEST_SECTION_MAP.values():
        covered.update(sections)
    return len(covered) >= 20
check("test_map_breadth", c4)


# 5. Artifact map covers at least 20 sections
def c5():
    from coverage_completeness import ARTIFACT_SECTION_MAP
    covered = set()
    for sections in ARTIFACT_SECTION_MAP.values():
        covered.update(sections)
    return len(covered) >= 20
check("artifact_map_breadth", c5)


# 6. Target sections J,S,M,O,Q,W all have gate coverage
def c6():
    from coverage_completeness import CoverageCompletenessAnalyzer
    a = CoverageCompletenessAnalyzer()
    result = a.check_target_sections(["J", "S", "M", "O", "Q", "W"])
    for sid in ["J", "S", "M", "O", "Q", "W"]:
        m = result["mappings"].get(sid, {})
        if not m.get("gates"):
            return False
    return True
check("target_sections_gate_coverage", c6)


# 7. Target sections J,S,M,O,Q,W all have test coverage
def c7():
    from coverage_completeness import CoverageCompletenessAnalyzer
    a = CoverageCompletenessAnalyzer()
    result = a.check_target_sections(["J", "S", "M", "O", "Q", "W"])
    for sid in ["J", "S", "M", "O", "Q", "W"]:
        m = result["mappings"].get(sid, {})
        if not m.get("test_families"):
            return False
    return True
check("target_sections_test_coverage", c7)


# 8. Target sections J,S,M,O,Q,W all have artifact coverage
def c8():
    from coverage_completeness import CoverageCompletenessAnalyzer
    a = CoverageCompletenessAnalyzer()
    result = a.check_target_sections(["J", "S", "M", "O", "Q", "W"])
    for sid in ["J", "S", "M", "O", "Q", "W"]:
        m = result["mappings"].get(sid, {})
        if not m.get("artifact_patterns"):
            return False
    return True
check("target_sections_artifact_coverage", c8)


# 9. Full completeness >= 80%
def c9():
    from coverage_completeness import CoverageCompletenessAnalyzer
    a = CoverageCompletenessAnalyzer()
    result = a.check_completeness()
    return result["completeness_pct"] >= 80.0
check("full_completeness_above_80pct", c9)


# 10. Artifact emission works
def c10():
    import tempfile
    from coverage_completeness import CoverageCompletenessAnalyzer
    a = CoverageCompletenessAnalyzer()
    with tempfile.TemporaryDirectory() as td:
        path = a.emit_artifact(td, ["J", "S", "M", "O", "Q", "W"])
        p = Path(path)
        if not p.exists():
            return False
        data = json.loads(p.read_text())
        return "completeness_pct" in data and "mappings" in data
check("artifact_emission", c10)


# ---- Report ----
ts = time.strftime("%Y%m%d-%H%M%S")
passed = sum(1 for c in checks if c["result"] == "PASS")
total = len(checks)
verdict = "PASS" if passed == total else "FAIL"

report = {
    "gate": "coverage-completeness",
    "timestamp": ts,
    "checks": checks,
    "passed": passed,
    "total": total,
    "verdict": verdict,
}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"coverage-completeness-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Coverage Completeness Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
