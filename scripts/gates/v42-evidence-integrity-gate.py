#!/usr/bin/env python3
"""
v4.2 Evidence Integrity Gate
==============================
Cross-cutting evidence checks with real filesystem/JSON validation.

5 checks:
  1. Gate matrix exists and parses as valid JSON
  2. All gates in matrix show PROMOTE verdict
  3. Test count meets inherited floor (753)
  4. All 3 epic gate artifacts present and show PASS
  5. Dual-pass scores meet floor (495/495, gap <= 6)
"""
import json
import os
import sys
import time
import glob
from datetime import datetime, timezone

GATE_ID = "v42-evidence-integrity-gate"
AUDIT = os.path.join("S:", "reports", "audit")
V42_BASELINE = os.path.join(AUDIT, "v4.2-baseline")
INHERITED_FLOOR = 753
DUAL_PASS_FLOOR = 495
MAX_GAP = 6


def latest_file(pattern):
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    return files[-1] if files else None


def check_gate_matrix_exists():
    """Check 1: Gate matrix exists and parses as valid JSON."""
    pattern = os.path.join(V42_BASELINE, "gate-matrix-v42-2*.json")
    path = latest_file(pattern)
    if not path:
        return False, "No gate-matrix-v42-*.json found"
    try:
        with open(path) as f:
            data = json.load(f)
        if "gates_passed" not in data or "gates_total" not in data:
            return False, f"Missing required fields in {os.path.basename(path)}"
        return True, f"OK: {os.path.basename(path)} ({data['gates_passed']}/{data['gates_total']})"
    except (json.JSONDecodeError, KeyError) as e:
        return False, f"Invalid JSON: {e}"


def check_all_gates_promote():
    """Check 2: All gates in matrix show PROMOTE verdict."""
    pattern = os.path.join(V42_BASELINE, "gate-matrix-v42-2*.json")
    path = latest_file(pattern)
    if not path:
        return False, "No gate matrix found"
    try:
        data = json.load(open(path))
        verdict = data.get("verdict", "UNKNOWN")
        passed = data.get("gates_passed", 0)
        total = data.get("gates_total", 0)
        hold = data.get("hold_reasons", [])
        if verdict != "PROMOTE":
            return False, f"Verdict={verdict}, hold_reasons={hold}"
        if passed != total:
            return False, f"Only {passed}/{total} gates passed"
        return True, f"OK: {passed}/{total} PROMOTE"
    except Exception as e:
        return False, f"Error: {e}"


def check_test_floor():
    """Check 3: Test count meets inherited floor (753)."""
    pattern = os.path.join(V42_BASELINE, "gate-matrix-v42-2*.json")
    path = latest_file(pattern)
    if not path:
        return False, "No gate matrix found"
    try:
        data = json.load(open(path))
        passed = data.get("unit_tests_passed", 0)
        failed = data.get("unit_tests_failed", -1)
        if passed < INHERITED_FLOOR:
            return False, f"Tests {passed} < floor {INHERITED_FLOOR}"
        if failed > 0:
            return False, f"Tests failed: {failed}"
        return True, f"OK: {passed} passed, {failed} failed (floor={INHERITED_FLOOR})"
    except Exception as e:
        return False, f"Error: {e}"


def check_epic_artifacts():
    """Check 4: All 3 epic gate artifacts present and show PASS."""
    patterns = [
        ("E1", os.path.join(AUDIT, "v42-epic1-identity-memory-*.json")),
        ("E2", os.path.join(AUDIT, "v42-epic2-chaos-recovery-*.json")),
        ("E3", os.path.join(AUDIT, "v42-epic3-repro-release-*.json")),
    ]
    missing = []
    failing = []
    for label, pat in patterns:
        path = latest_file(pat)
        if not path:
            missing.append(label)
            continue
        try:
            data = json.load(open(path))
            if data.get("verdict") != "PASS":
                failing.append(f"{label}={data.get('verdict')}")
            if data.get("passed", 0) != 10:
                failing.append(f"{label} {data.get('passed',0)}/10")
        except Exception as e:
            failing.append(f"{label} error: {e}")

    if missing:
        return False, f"Missing: {', '.join(missing)}"
    if failing:
        return False, f"Failures: {', '.join(failing)}"
    return True, "OK: E1/E2/E3 all PASS 10/10"


def check_dual_pass():
    """Check 5: Dual-pass scores meet floor (495/495, gap <= 6)."""
    pattern = os.path.join(V42_BASELINE, "FINAL_SCORECARD-v42-*.json")
    path = latest_file(pattern)
    if not path:
        return False, "No FINAL_SCORECARD found"
    try:
        data = json.load(open(path))
        std = data.get("standard_total", 0)
        con = data.get("conservative_total", 0)
        gap = data.get("gap", 999)
        if std < DUAL_PASS_FLOOR:
            return False, f"Standard {std} < {DUAL_PASS_FLOOR}"
        if con < DUAL_PASS_FLOOR:
            return False, f"Conservative {con} < {DUAL_PASS_FLOOR}"
        if gap > MAX_GAP:
            return False, f"Gap {gap} > {MAX_GAP}"
        return True, f"OK: std={std}, con={con}, gap={gap}"
    except Exception as e:
        return False, f"Error: {e}"


CHECKS = [
    ("evidence_manifest_exists", check_gate_matrix_exists),
    ("all_gates_promote", check_all_gates_promote),
    ("test_floor_met", check_test_floor),
    ("epic_gate_reports_present", check_epic_artifacts),
    ("dual_pass_scores_meet_floor", check_dual_pass),
]


def main():
    t0 = time.time()
    passed = 0
    results = []

    for check_name, check_fn in CHECKS:
        ok, detail = check_fn()
        verdict = "PASS" if ok else "FAIL"
        results.append({"check": check_name, "verdict": verdict, "detail": detail})
        print(f"  [{verdict}] {check_name}: {detail}")
        if ok:
            passed += 1

    total = len(CHECKS)
    elapsed = round(time.time() - t0, 3)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = {
        "epic": "cross-cutting",
        "gate": GATE_ID,
        "checks": total,
        "passed": passed,
        "verdict": "PASS" if passed == total else "FAIL",
        "elapsed_s": elapsed,
        "retries": 0,
        "failure_class": None,
        "results": results,
        "timestamp": ts,
    }

    os.makedirs(AUDIT, exist_ok=True)
    out_path = os.path.join(AUDIT, f"v42-evidence-integrity-{ts}.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{passed}/{total} checks PASS")
    print(f"Artifact: {out_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
