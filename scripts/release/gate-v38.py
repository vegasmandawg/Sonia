"""
SONIA v3.8.0 Promotion Gate (M0: Bootstrap + Hardening)
=====================================================
Inherits the full v3.7 floor (24 gates, 299 unit tests) and adds v3.8 delta gates.

Usage:
    python gate-v38.py [--output-dir S:\\reports\\audit\\v3.8-baseline]
    python gate-v38.py --floor-only   # run only inherited floor

Inherited Floor (v3.7): 24 gates
v3.8 Delta Gates: TBD (wired per-epic as scope is defined)

Hardening (M0):
  - One retry for gate subprocesses that fail with empty/ambiguous output
  - Persists stdout/stderr + cwd + elapsed time per gate in matrix artifact
  - Classifies failures as deterministic_fail vs transient_fail
  - If retry passes, marks gate PASS_WITH_RETRY and includes evidence
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


def _is_ambiguous_failure(returncode, stdout, stderr):
    """Detect failures that may be transient (empty output, subprocess noise)."""
    combined = (stdout or "") + (stderr or "")
    if returncode != 0:
        # Empty or near-empty output suggests subprocess issue, not real failure
        if len(combined.strip()) < 20:
            return True
        # Pydantic/deprecation warnings in stderr with no real failure info
        if "DeprecatedSince" in stderr and "FAIL" not in stdout:
            return True
        # Timeout-like patterns without explicit FAIL
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


def run_gate_script(gate_file):
    """Run a gate script with retry logic. Returns a rich result dict."""
    gate_path = GATE_DIR / gate_file
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
        # Parse check count
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

    # Check if failure is ambiguous (candidate for retry)
    if _is_ambiguous_failure(rc, stdout, stderr):
        # Attempt 2 (retry)
        time.sleep(2)  # brief cooldown
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
            # Retry also failed -- deterministic
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

    # Deterministic failure (clear output, no retry)
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
    print("  SONIA v3.8 Promotion Gate (hardened)")
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
        "failure_class": None if unit_ok else "deterministic_fail",
        "attempts": 1,
        "duration_s": dt,
        "cwd": str(REPO_ROOT),
    })

    # ---- Inherited baseline gates ----
    print(f"\n[2/3] Running {INHERITED_FLOOR_COUNT} inherited baseline gates...")
    floor_pass = 0
    floor_fail = 0
    retried = 0
    for gate_file in INHERITED_GATES:
        gate_result = run_gate_script(gate_file)
        gate_result["gate"] = gate_file
        gate_result["category"] = "inherited"
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

    floor_ok = floor_fail == 0
    retry_note = f" ({retried} retried)" if retried else ""
    print(f"\n  Inherited floor: {floor_pass}/{INHERITED_FLOOR_COUNT}"
          f" {'PASS' if floor_ok else 'FAIL'}{retry_note}")

    # ---- v3.8 delta gates ----
    delta_pass = 0
    delta_fail = 0
    if not args.floor_only and DELTA_GATES:
        print(f"\n[3/3] Running {DELTA_GATE_COUNT} v3.8 delta gates...")
        for gate_file, label in DELTA_GATES:
            gate_result = run_gate_script(gate_file)
            gate_result["gate"] = gate_file
            gate_result["category"] = "delta"
            gate_result["label"] = label
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
        print(f"\n[3/3] No delta gates wired yet (or --floor-only mode)")

    # ---- Verdict ----
    total_pass = (1 if unit_ok else 0) + floor_pass + delta_pass
    total_count = 1 + INHERITED_FLOOR_COUNT + (DELTA_GATE_COUNT if not args.floor_only else 0)
    all_green = unit_ok and floor_ok and delta_fail == 0

    verdict = "PROMOTE" if all_green else "HOLD"

    report = {
        "schema_version": "5.1",
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
        "retried_gates": retried,
        "verdict": verdict,
        "gates": results,
    }

    report_path = output_dir / f"gate-matrix-v38-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 60}")
    print(f"  {total_pass}/{total_count} gates passed -- {verdict}")
    if retried:
        print(f"  ({retried} gate(s) passed with retry)")
    if args.floor_only:
        print(f"  (floor-only mode: v3.8 delta gates skipped)")
    print(f"  Report: {report_path}")
    print(f"{'=' * 60}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
