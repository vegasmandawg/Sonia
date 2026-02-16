"""
SONIA v3.8.0 Promotion Gate (M0: Bootstrap)
=====================================================
Inherits the full v3.7 floor (24 gates, 299 unit tests) and adds v3.8 delta gates.

Usage:
    python gate-v38.py [--output-dir S:\\reports\\audit\\v3.8-baseline]
    python gate-v38.py --floor-only   # run only inherited floor

Inherited Floor (v3.7): 24 gates
  auth-posture-gate, auth-surface-gate, backup-restore-drill,
  cleanroom-parity-gate, consolidated-preaudit, drill-determinism-gate,
  fallback-behavior-gate, incident-bundle-gate, incident-completeness-gate,
  incident-lineage-gate, memory-silo-gate, output-budget-gate,
  perf-budget-gate, policy-enforcement-gate, rate-limiter-gate,
  recovery-determinism-gate, regression-guard-gate, release-integrity-gate,
  restore-integrity-gate, runtime-qos-gate, secret-scan-gate,
  session-isolation-gate, traceability-gate, unit-test-layer-gate

v3.8 Delta Gates: TBD (wired per-epic as scope is defined)
"""
import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("S:/")
PYTHON = str(REPO_ROOT / "envs" / "sonia-core" / "python.exe")
GATE_DIR = REPO_ROOT / "scripts" / "gates"
UNIT_TEST_DIR = REPO_ROOT / "tests" / "unit"

EXPECTED_BRANCH = "v3.8-dev"

# ---- Inherited baseline gates (24 from v3.7) --------------------------------

INHERITED_GATES = [
    "auth-posture-gate.py",
    "auth-surface-gate.py",
    "backup-restore-drill.py",
    "cleanroom-parity-gate.py",
    "consolidated-preaudit.py",
    "drill-determinism-gate.py",
    "fallback-behavior-gate.py",
    "incident-bundle-gate.py",
    "incident-completeness-gate.py",
    "incident-lineage-gate.py",
    "memory-silo-gate.py",
    "output-budget-gate.py",
    "perf-budget-gate.py",
    "policy-enforcement-gate.py",
    "rate-limiter-gate.py",
    "recovery-determinism-gate.py",
    "regression-guard-gate.py",
    "release-integrity-gate.py",
    "restore-integrity-gate.py",
    "runtime-qos-gate.py",
    "secret-scan-gate.py",
    "session-isolation-gate.py",
    "traceability-gate.py",
    "unit-test-layer-gate.py",
]

INHERITED_FLOOR_COUNT = len(INHERITED_GATES)
INHERITED_UNIT_TEST_FLOOR = 299

# ---- v3.8 delta gates (add here as epics are wired) -------------------------

DELTA_GATES = [
    # ("delta-gate-name.py", "Epic label"),
]

DELTA_GATE_COUNT = len(DELTA_GATES)
TOTAL_GATES = INHERITED_FLOOR_COUNT + DELTA_GATE_COUNT


def run_gate_script(gate_file):
    """Run a single gate script, return (passed: bool, detail: str)."""
    gate_path = GATE_DIR / gate_file
    if not gate_path.exists():
        return False, f"gate script not found: {gate_path}"
    cmd = [PYTHON, str(gate_path)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=600,
        )
        output = result.stdout + result.stderr
        # Gate scripts print "X / Y checks PASS" on success
        if result.returncode == 0:
            # Extract check count if available
            m = re.search(r"(\d+)\s*/\s*(\d+)\s*checks?\s*PASS", output)
            if m:
                return True, f"{m.group(1)}/{m.group(2)} checks PASS"
            return True, "PASS"
        else:
            # Extract failure detail
            lines = output.strip().split("\n")
            last = lines[-1] if lines else "unknown failure"
            return False, f"FAIL: {last[:200]}"
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (300s)"
    except Exception as e:
        return False, f"ERROR: {e}"


def run_unit_tests():
    """Run all unit tests, return (passed_count, failed_count, output)."""
    cmd = [PYTHON, "-m", "pytest", str(UNIT_TEST_DIR), "-v", "--tb=short"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=600,
        )
        output = result.stdout + result.stderr
        passed = 0
        failed = 0
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
        return passed, failed, output
    except subprocess.TimeoutExpired:
        return 0, -1, "TIMEOUT"
    except Exception as e:
        return 0, -1, str(e)


def main():
    parser = argparse.ArgumentParser(description="SONIA v3.8 Promotion Gate")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "reports" / "audit" / "v3.8-baseline"),
    )
    parser.add_argument(
        "--floor-only", action="store_true",
        help="Run only inherited floor, skip v3.8 delta gates",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    results = []

    # ---- Unit test floor check ----
    print("=" * 60)
    print("  SONIA v3.8 Promotion Gate")
    print("=" * 60)
    print(f"\n[1/3] Running unit test floor check (>={INHERITED_UNIT_TEST_FLOOR} required)...")
    t0 = time.time()
    passed, failed, test_output = run_unit_tests()
    dt = round(time.time() - t0, 3)
    unit_ok = passed >= INHERITED_UNIT_TEST_FLOOR and failed == 0
    status = "PASS" if unit_ok else "FAIL"
    print(f"  [{status}] Unit tests: {passed} passed, {failed} failed ({dt}s)")
    results.append({
        "gate": "UNIT_TEST_FLOOR",
        "passed": unit_ok,
        "detail": f"{passed} passed, {failed} failed (floor: {INHERITED_UNIT_TEST_FLOOR})",
        "duration_s": dt,
    })

    # ---- Inherited baseline gates ----
    print(f"\n[2/3] Running {INHERITED_FLOOR_COUNT} inherited baseline gates...")
    floor_pass = 0
    floor_fail = 0
    for gate_file in INHERITED_GATES:
        t0 = time.time()
        ok, detail = run_gate_script(gate_file)
        dt = round(time.time() - t0, 3)
        results.append({
            "gate": gate_file,
            "passed": ok,
            "detail": detail,
            "duration_s": dt,
            "category": "inherited",
        })
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {gate_file}: {detail} ({dt}s)")
        if ok:
            floor_pass += 1
        else:
            floor_fail += 1

    floor_ok = floor_fail == 0
    print(f"\n  Inherited floor: {floor_pass}/{INHERITED_FLOOR_COUNT}"
          f" {'PASS' if floor_ok else 'FAIL'}")

    # ---- v3.8 delta gates ----
    delta_pass = 0
    delta_fail = 0
    if not args.floor_only and DELTA_GATES:
        print(f"\n[3/3] Running {DELTA_GATE_COUNT} v3.8 delta gates...")
        for gate_file, label in DELTA_GATES:
            t0 = time.time()
            ok, detail = run_gate_script(gate_file)
            dt = round(time.time() - t0, 3)
            results.append({
                "gate": gate_file,
                "passed": ok,
                "detail": detail,
                "duration_s": dt,
                "category": "delta",
                "label": label,
            })
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {gate_file} ({label}): {detail} ({dt}s)")
            if ok:
                delta_pass += 1
            else:
                delta_fail += 1
    else:
        print(f"\n[3/3] No delta gates wired yet (or --floor-only mode)")

    # ---- Verdict ----
    total_pass = (1 if unit_ok else 0) + floor_pass + delta_pass
    total_count = 1 + INHERITED_FLOOR_COUNT + (DELTA_GATE_COUNT if not args.floor_only else 0)
    all_green = unit_ok and floor_ok and delta_fail == 0

    verdict = "PROMOTE" if all_green else "HOLD"

    report = {
        "schema_version": "5.0",
        "version": "3.8.0-dev",
        "branch": EXPECTED_BRANCH,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gates_passed": total_pass,
        "gates_total": total_count,
        "inherited_floor": INHERITED_FLOOR_COUNT,
        "inherited_unit_test_floor": INHERITED_UNIT_TEST_FLOOR,
        "unit_tests_passed": passed,
        "unit_tests_failed": failed,
        "delta_gates_wired": DELTA_GATE_COUNT,
        "floor_only": args.floor_only,
        "verdict": verdict,
        "gates": results,
    }

    report_path = output_dir / f"gate-matrix-v38-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 60}")
    print(f"  {total_pass}/{total_count} gates passed -- {verdict}")
    if args.floor_only:
        print(f"  (floor-only mode: v3.8 delta gates skipped)")
    print(f"  Report: {report_path}")
    print(f"{'=' * 60}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
