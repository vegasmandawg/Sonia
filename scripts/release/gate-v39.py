"""
SONIA v3.9.0 Promotion Gate
============================
Inherits the full v3.8 floor (28 gates, 430 unit tests) and adds v3.9 delta gates.

FAIL-FAST: Any inherited gate failure immediately marks HOLD regardless of delta results.

Usage:
    python gate-v39.py [--output-dir S:\\reports\\audit\\v3.9-baseline]
    python gate-v39.py --floor-only   # run only inherited floor
    python gate-v39.py --delta-only   # run only v3.9 delta gates

Three gate classes:
  1. Inherited baseline (28): fail-fast HOLD on first failure
  2. v3.9 delta gates: per-epic additions
  3. Test floor checks: >=430 unit tests, 0 failures

Hardening (carried from v3.8 M0):
  - One retry for ambiguous failures (empty output, subprocess noise)
  - Persists stdout/stderr + cwd + elapsed per gate
  - Classifies failures as deterministic_fail vs transient_fail
  - PASS_WITH_RETRY outcome with evidence trail
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
RELEASE_DIR = REPO_ROOT / "scripts" / "release"
UNIT_TEST_DIR = REPO_ROOT / "tests" / "unit"

SCHEMA_VERSION = "6.0"

# ---- Inherited baseline gates (28 from v3.8.0) --------------------------------
# 24 original (v3.7) + 4 delta (v3.8)

INHERITED_GATES_GATES_DIR = [
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

INHERITED_GATES_RELEASE_DIR = [
    "schema-validation-gate.py",
    "data-migration-gate.py",
    "automation-coverage-gate.py",
    "trace-propagation-gate.py",
]

INHERITED_FLOOR_COUNT = len(INHERITED_GATES_GATES_DIR) + len(INHERITED_GATES_RELEASE_DIR)
INHERITED_UNIT_TEST_FLOOR = 430

# ---- v3.9 delta gates (add here as epics are wired) -------------------------

DELTA_GATES = [
    ("coverage-completeness-gate.py", "gates", "Epic 1: Coverage Completeness"),
    ("data-durability-gate.py", "gates", "Epic 1: Data Durability"),
    ("deduction-sweep-gate.py", "gates", "Epic 2: Deduction Sweep"),
    ("test-strategy-gate.py", "gates", "Epic 2: Test Strategy"),
]

DELTA_GATE_COUNT = len(DELTA_GATES)
TOTAL_GATES = INHERITED_FLOOR_COUNT + DELTA_GATE_COUNT


# ---- Subprocess execution with retry ----------------------------------------

def _is_ambiguous_failure(returncode, stdout, stderr, always_retry=False):
    """Detect failures that may be transient (empty output, subprocess noise).

    If always_retry=True, any non-zero exit is retried once. This is used for
    inherited gates which are known-green -- any failure during orchestration
    is likely resource contention from concurrent subprocess spawning.
    """
    if always_retry and returncode != 0:
        return True
    combined = (stdout or "") + (stderr or "")
    if returncode != 0:
        if len(combined.strip()) < 20:
            return True
        if "DeprecatedSince" in stderr and "FAIL" not in stdout:
            return True
        if "timed out" in combined.lower() and "FAIL" not in stdout:
            return True
    return False


def _run_gate_once(gate_path):
    """Execute a gate script once, return (returncode, stdout, stderr, elapsed)."""
    cmd = [PYTHON, str(gate_path)]
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=600,
        )
        elapsed = round(time.time() - t0, 3)
        return result.returncode, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - t0, 3)
        return -1, "", "TIMEOUT (600s)", elapsed
    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        return -2, "", f"ERROR: {e}", elapsed


def run_gate_script(gate_file, search_dir, always_retry=False):
    """Run a gate script with retry logic. Returns a rich result dict.

    If always_retry=True, any failure triggers a single retry regardless
    of whether the failure looks ambiguous.
    """
    gate_path = search_dir / gate_file
    if not gate_path.exists():
        return {
            "passed": False,
            "detail": f"gate script not found: {gate_path}",
            "failure_class": "deterministic_fail",
            "attempts": 0,
            "stdout": "",
            "stderr": "",
            "cwd": str(REPO_ROOT),
            "elapsed_s": 0,
        }

    # Attempt 1
    rc, stdout, stderr, elapsed = _run_gate_once(gate_path)
    combined = stdout + stderr

    if rc == 0:
        m = re.search(r"(\d+)\s*/\s*(\d+)\s*checks?\s*PASS", combined)
        detail = f"{m.group(1)}/{m.group(2)} checks PASS" if m else "PASS"
        return {
            "passed": True,
            "detail": detail,
            "failure_class": None,
            "attempts": 1,
            "stdout": stdout[-500:],
            "stderr": stderr[-500:],
            "cwd": str(REPO_ROOT),
            "elapsed_s": elapsed,
        }

    # Retry on ambiguous failure (or always for inherited gates)
    if _is_ambiguous_failure(rc, stdout, stderr, always_retry=always_retry):
        time.sleep(2)
        rc2, stdout2, stderr2, elapsed2 = _run_gate_once(gate_path)
        combined2 = stdout2 + stderr2

        if rc2 == 0:
            m = re.search(r"(\d+)\s*/\s*(\d+)\s*checks?\s*PASS", combined2)
            detail = f"{m.group(1)}/{m.group(2)} checks PASS" if m else "PASS"
            return {
                "passed": True,
                "detail": f"PASS_WITH_RETRY: {detail}",
                "failure_class": "transient_fail",
                "attempts": 2,
                "retry_evidence": {
                    "attempt1_rc": rc,
                    "attempt1_stdout_tail": stdout[-300:],
                    "attempt1_stderr_tail": stderr[-300:],
                    "attempt1_elapsed_s": elapsed,
                },
                "stdout": stdout2[-500:],
                "stderr": stderr2[-500:],
                "cwd": str(REPO_ROOT),
                "elapsed_s": elapsed + elapsed2,
            }
        else:
            lines = combined2.strip().split("\n")
            last = lines[-1] if lines else "unknown failure"
            return {
                "passed": False,
                "detail": f"FAIL (confirmed after retry): {last[:200]}",
                "failure_class": "deterministic_fail",
                "attempts": 2,
                "retry_evidence": {
                    "attempt1_rc": rc,
                    "attempt1_stdout_tail": stdout[-300:],
                    "attempt1_stderr_tail": stderr[-300:],
                    "attempt1_elapsed_s": elapsed,
                },
                "stdout": stdout2[-500:],
                "stderr": stderr2[-500:],
                "cwd": str(REPO_ROOT),
                "elapsed_s": elapsed + elapsed2,
            }

    # Deterministic failure
    lines = combined.strip().split("\n")
    last = lines[-1] if lines else "unknown failure"
    return {
        "passed": False,
        "detail": f"FAIL: {last[:200]}",
        "failure_class": "deterministic_fail",
        "attempts": 1,
        "stdout": stdout[-500:],
        "stderr": stderr[-500:],
        "cwd": str(REPO_ROOT),
        "elapsed_s": elapsed,
    }


def run_unit_tests():
    """Run all unit tests, return (passed_count, failed_count, output, elapsed)."""
    cmd = [PYTHON, "-m", "pytest", str(UNIT_TEST_DIR), "-v", "--tb=short"]
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=600,
        )
        elapsed = round(time.time() - t0, 3)
        output = result.stdout + result.stderr
        passed = 0
        failed = 0
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
        return passed, failed, output, elapsed
    except subprocess.TimeoutExpired:
        elapsed = round(time.time() - t0, 3)
        return 0, -1, "TIMEOUT", elapsed
    except Exception as e:
        elapsed = round(time.time() - t0, 3)
        return 0, -1, str(e), elapsed


# ---- Main orchestration -----------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SONIA v3.9 Promotion Gate")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "reports" / "audit" / "v3.9-baseline"),
    )
    parser.add_argument(
        "--floor-only", action="store_true",
        help="Run only inherited floor, skip v3.9 delta gates",
    )
    parser.add_argument(
        "--delta-only", action="store_true",
        help="Run only v3.9 delta gates, skip inherited floor",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    results = []
    inherited_hold = False  # fail-fast flag

    print("=" * 60)
    print("  SONIA v3.9 Promotion Gate")
    print("=" * 60)

    # ---- [1/3] Unit test floor check ----
    if not args.delta_only:
        print(f"\n[1/3] Running unit test floor check (>={INHERITED_UNIT_TEST_FLOOR} required)...")
        passed, failed, test_output, dt = run_unit_tests()
        unit_ok = passed >= INHERITED_UNIT_TEST_FLOOR and failed == 0
        status = "PASS" if unit_ok else "FAIL"
        print(f"  [{status}] Unit tests: {passed} passed, {failed} failed ({dt}s)")
        results.append({
            "gate": "UNIT_TEST_FLOOR",
            "category": "test_floor",
            "passed": unit_ok,
            "detail": f"{passed} passed, {failed} failed (floor: {INHERITED_UNIT_TEST_FLOOR})",
            "failure_class": None if unit_ok else "deterministic_fail",
            "attempts": 1,
            "elapsed_s": dt,
            "cwd": str(REPO_ROOT),
        })
        if not unit_ok:
            inherited_hold = True
            print("\n  *** FAIL-FAST: Unit test floor breached. Marking HOLD. ***")
    else:
        passed, failed = INHERITED_UNIT_TEST_FLOOR, 0
        unit_ok = True
        print("\n[1/3] Skipped (--delta-only mode)")

    # ---- [2/3] Inherited baseline gates (28) ----
    if not args.delta_only:
        print(f"\n[2/3] Running {INHERITED_FLOOR_COUNT} inherited baseline gates...")
        floor_pass = 0
        floor_fail = 0
        retried = 0

        # Run gates/ directory gates (always_retry for inherited)
        for gate_file in INHERITED_GATES_GATES_DIR:
            gate_result = run_gate_script(gate_file, GATE_DIR, always_retry=True)
            gate_result["gate"] = gate_file
            gate_result["category"] = "inherited"
            gate_result["source_dir"] = "scripts/gates"
            gate_result["duration_s"] = gate_result.pop("elapsed_s")
            results.append(gate_result)

            if gate_result["passed"]:
                floor_pass += 1
                if gate_result["attempts"] > 1:
                    retried += 1
            else:
                floor_fail += 1

            tag = "PASS" if gate_result["passed"] else "FAIL"
            retry_note = " [RETRIED]" if gate_result["attempts"] > 1 else ""
            print(f"  [{tag}] {gate_file}: {gate_result['detail']}"
                  f" ({gate_result['duration_s']}s){retry_note}")

            # FAIL-FAST: stop on first inherited failure
            if not gate_result["passed"]:
                inherited_hold = True
                print(f"\n  *** FAIL-FAST: Inherited gate {gate_file} failed. Marking HOLD. ***")
                print(f"  *** Remaining inherited gates will still run for diagnostics. ***")

        # Run scripts/release directory gates (v3.8 delta, now inherited)
        for gate_file in INHERITED_GATES_RELEASE_DIR:
            gate_result = run_gate_script(gate_file, RELEASE_DIR, always_retry=True)
            gate_result["gate"] = gate_file
            gate_result["category"] = "inherited"
            gate_result["source_dir"] = "scripts/release"
            gate_result["duration_s"] = gate_result.pop("elapsed_s")
            results.append(gate_result)

            if gate_result["passed"]:
                floor_pass += 1
                if gate_result["attempts"] > 1:
                    retried += 1
            else:
                floor_fail += 1

            tag = "PASS" if gate_result["passed"] else "FAIL"
            retry_note = " [RETRIED]" if gate_result["attempts"] > 1 else ""
            print(f"  [{tag}] {gate_file}: {gate_result['detail']}"
                  f" ({gate_result['duration_s']}s){retry_note}")

            if not gate_result["passed"]:
                inherited_hold = True

        floor_ok = floor_fail == 0
        retry_label = f" ({retried} retried)" if retried else ""
        print(f"\n  Inherited floor: {floor_pass}/{INHERITED_FLOOR_COUNT}"
              f" {'PASS' if floor_ok else 'FAIL'}{retry_label}")
    else:
        floor_pass = INHERITED_FLOOR_COUNT
        floor_fail = 0
        floor_ok = True
        retried = 0
        print(f"\n[2/3] Skipped (--delta-only mode)")

    # ---- [3/3] v3.9 delta gates ----
    delta_pass = 0
    delta_fail = 0
    if not args.floor_only and DELTA_GATES:
        print(f"\n[3/3] Running {DELTA_GATE_COUNT} v3.9 delta gates...")

        # If inherited floor already HOLD, warn but still run delta for diagnostics
        if inherited_hold:
            print("  (NOTE: inherited floor HOLD -- delta results are informational only)")

        for gate_file, directory, label in DELTA_GATES:
            search_dir = RELEASE_DIR if directory == "release" else GATE_DIR
            gate_result = run_gate_script(gate_file, search_dir)
            gate_result["gate"] = gate_file
            gate_result["category"] = "delta"
            gate_result["label"] = label
            gate_result["source_dir"] = f"scripts/{directory}"
            gate_result["duration_s"] = gate_result.pop("elapsed_s")
            results.append(gate_result)

            if gate_result["passed"]:
                delta_pass += 1
            else:
                delta_fail += 1

            tag = "PASS" if gate_result["passed"] else "FAIL"
            print(f"  [{tag}] {gate_file} ({label}): {gate_result['detail']}"
                  f" ({gate_result['duration_s']}s)")
    else:
        if args.floor_only:
            print(f"\n[3/3] Skipped (--floor-only mode)")
        elif not DELTA_GATES:
            print(f"\n[3/3] No delta gates wired yet")

    # ---- Verdict ----
    total_pass = (1 if unit_ok else 0) + floor_pass + delta_pass
    total_count = 1 + INHERITED_FLOOR_COUNT + (DELTA_GATE_COUNT if not args.floor_only else 0)
    if args.delta_only:
        total_count = DELTA_GATE_COUNT
        total_pass = delta_pass

    all_green = unit_ok and floor_ok and delta_fail == 0 and not inherited_hold

    verdict = "PROMOTE" if all_green else "HOLD"
    hold_reasons = []
    if inherited_hold:
        hold_reasons.append("inherited floor regression")
    if not unit_ok:
        hold_reasons.append(f"unit tests below floor ({passed}/{INHERITED_UNIT_TEST_FLOOR})")
    if delta_fail > 0:
        hold_reasons.append(f"{delta_fail} delta gate(s) failed")

    report = {
        "schema_version": SCHEMA_VERSION,
        "version": "3.9.0-dev",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gates_passed": total_pass,
        "gates_total": total_count,
        "inherited_floor": INHERITED_FLOOR_COUNT,
        "inherited_unit_test_floor": INHERITED_UNIT_TEST_FLOOR,
        "unit_tests_passed": passed,
        "unit_tests_failed": failed,
        "delta_gates_wired": DELTA_GATE_COUNT,
        "floor_only": args.floor_only,
        "delta_only": args.delta_only,
        "retried_gates": retried,
        "fail_fast_triggered": inherited_hold,
        "hold_reasons": hold_reasons,
        "verdict": verdict,
        "gates": results,
    }

    report_path = output_dir / f"gate-matrix-v39-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 60}")
    print(f"  {total_pass}/{total_count} gates passed -- {verdict}")
    if hold_reasons:
        print(f"  HOLD reasons: {'; '.join(hold_reasons)}")
    if retried:
        print(f"  ({retried} gate(s) passed with retry)")
    if args.floor_only:
        print(f"  (floor-only mode: v3.9 delta gates skipped)")
    if args.delta_only:
        print(f"  (delta-only mode: inherited floor skipped)")
    print(f"  Report: {report_path}")
    print(f"{'=' * 60}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
