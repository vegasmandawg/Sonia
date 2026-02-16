"""
SONIA v4.0.0 Promotion Gate
============================
Schema v7.0 — three gate classes (A/B/C), retry classifier, per-gate telemetry.

Inherits the full v3.9 floor (33 gates, 523 unit tests) and adds v4.0 delta gates.

FAIL-FAST: Any Class-A gate failure immediately marks HOLD.

Gate Classes:
  A — Inherited baseline (33 from v3.9.0): fail-fast, always_retry
  B — v4.0 delta gates (epic-owned): per-epic additions
  C — Cross-cutting gates (evidence integrity, test budgets): structural checks

Usage:
    python gate-v40.py [--output-dir DIR]
    python gate-v40.py --floor-only    # Class A only
    python gate-v40.py --delta-only    # Class B + C only

Hardening:
  - One retry for ambiguous failures (empty output, subprocess noise)
  - Persists stdout/stderr + cwd + elapsed per gate
  - Classifies failures: deterministic_fail | transient_fail | timeout | not_found
  - PASS_WITH_RETRY outcome with evidence trail
  - Per-gate telemetry: start_time, end_time, duration_s, attempts, memory_kb
"""
import argparse
import json
import os
import random
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

SCHEMA_VERSION = "7.0"
VERSION = "4.0.0-dev"

# ---- Class A: Inherited baseline gates (33 from v3.9.0) ----------------------
# 24 original (v3.7) + 4 delta (v3.8) + 4 delta (v3.9) + 1 test floor

CLASS_A_GATES_DIR = [
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

CLASS_A_GATES_RELEASE_DIR = [
    "schema-validation-gate.py",
    "data-migration-gate.py",
    "automation-coverage-gate.py",
    "trace-propagation-gate.py",
]

CLASS_A_GATES_V39_DELTA = [
    ("coverage-completeness-gate.py", "gates", "v3.9 E1: Coverage Completeness"),
    ("data-durability-gate.py", "gates", "v3.9 E1: Data Durability"),
    ("deduction-sweep-gate.py", "gates", "v3.9 E2: Deduction Sweep"),
    ("test-strategy-gate.py", "gates", "v3.9 E2: Test Strategy"),
]

CLASS_A_COUNT = (len(CLASS_A_GATES_DIR) + len(CLASS_A_GATES_RELEASE_DIR)
                 + len(CLASS_A_GATES_V39_DELTA))
INHERITED_UNIT_TEST_FLOOR = 523

# ---- Class B: v4.0 delta gates (epic-owned) ----------------------------------

CLASS_B_GATES = [
    ("v40-epic1-gate.py", "gates", "E1: Session & Memory Governance"),
    ("v40-epic2-gate.py", "gates", "E2: Recovery, Incident Lineage, Determinism"),
    ("v40-epic3-gate.py", "gates", "E3: Runtime QoS, Contract Fidelity, Release"),
]

CLASS_B_COUNT = len(CLASS_B_GATES)

# ---- Class C: Cross-cutting gates --------------------------------------------

CLASS_C_GATES = [
    ("v40-evidence-integrity-gate.py", "gates", "Evidence Integrity"),
]

CLASS_C_COUNT = len(CLASS_C_GATES)

TOTAL_GATES = CLASS_A_COUNT + CLASS_B_COUNT + CLASS_C_COUNT  # + 1 for test floor


# ---- Retry classifier --------------------------------------------------------

class FailureClass:
    DETERMINISTIC = "deterministic_fail"
    TRANSIENT = "transient_fail"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"


def _classify_failure(returncode, stdout, stderr, always_retry=False):
    """Classify failure type and determine if retry is warranted.

    Returns (failure_class, should_retry).
    """
    combined = (stdout or "") + (stderr or "")

    if returncode == -1:  # timeout
        return FailureClass.TIMEOUT, False

    if always_retry and returncode != 0:
        return FailureClass.TRANSIENT, True

    if returncode != 0:
        # Empty or near-empty output — likely subprocess contention
        if len(combined.strip()) < 20:
            return FailureClass.TRANSIENT, True
        # Deprecation warnings without actual FAIL
        if "DeprecatedSince" in stderr and "FAIL" not in stdout:
            return FailureClass.TRANSIENT, True
        # Timeout-like messages
        if "timed out" in combined.lower() and "FAIL" not in stdout:
            return FailureClass.TRANSIENT, True

    return FailureClass.DETERMINISTIC, False


# ---- Subprocess execution with retry + backoff jitter -----------------------

# Backoff jitter range for retry delay (seconds).  Randomized to reduce
# thundering-herd contention when many gates run sequentially and hit the
# same subprocess resources (pytest, sqlite, file I/O).
RETRY_BASE_DELAY = 2.0
RETRY_JITTER_MAX = 1.5  # delay = base + uniform(0, jitter_max)


def _backoff_delay():
    """Return a randomized retry delay to de-correlate concurrent retries."""
    return RETRY_BASE_DELAY + random.uniform(0, RETRY_JITTER_MAX)


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


def _extract_detail(combined):
    """Pull check-count detail from gate output, or default to PASS."""
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*checks?\s*PASS", combined)
    return f"{m.group(1)}/{m.group(2)} checks PASS" if m else "PASS"


def _attempt_record(rc, stdout, stderr, elapsed):
    """Build a compact attempt log dict (preserved in both-attempt evidence)."""
    return {
        "returncode": rc,
        "stdout_tail": (stdout or "")[-400:],
        "stderr_tail": (stderr or "")[-400:],
        "elapsed_s": elapsed,
    }


def run_gate_script(gate_file, search_dir, always_retry=False):
    """Run a gate script with controlled retry + backoff jitter.

    Retry policy:
      - If always_retry=True (Class A inherited gates), any non-zero exit
        triggers one retry after randomized backoff.
      - Otherwise, only ambiguous failures (empty output, deprecation noise,
        timeout-like messages) trigger retry.
      - Both attempt logs are preserved in the result for audit.

    Classification:
      - transient_fail: retry succeeded (PASS_WITH_RETRY)
      - deterministic_fail: retry also failed, or failure is unambiguous
      - timeout: subprocess exceeded 600s hard limit
      - not_found: gate script does not exist on disk
    """
    gate_path = search_dir / gate_file
    if not gate_path.exists():
        return {
            "passed": False,
            "detail": f"gate script not found: {gate_path}",
            "failure_class": FailureClass.NOT_FOUND,
            "attempts": 0,
            "attempt_log": [],
            "stdout": "",
            "stderr": "",
            "cwd": str(REPO_ROOT),
            "duration_s": 0,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": datetime.now(timezone.utc).isoformat(),
        }

    start_time = datetime.now(timezone.utc).isoformat()

    # ---- Attempt 1 ----
    rc, stdout, stderr, elapsed = _run_gate_once(gate_path)
    attempt1 = _attempt_record(rc, stdout, stderr, elapsed)
    combined = stdout + stderr

    if rc == 0:
        return {
            "passed": True,
            "detail": _extract_detail(combined),
            "failure_class": None,
            "attempts": 1,
            "attempt_log": [attempt1],
            "stdout": stdout[-500:],
            "stderr": stderr[-500:],
            "cwd": str(REPO_ROOT),
            "duration_s": elapsed,
            "start_time": start_time,
            "end_time": datetime.now(timezone.utc).isoformat(),
        }

    # ---- Classify and decide retry ----
    fail_class, should_retry = _classify_failure(rc, stdout, stderr, always_retry)

    if should_retry:
        # Backoff with jitter to reduce subprocess contention
        jitter_delay = _backoff_delay()
        time.sleep(jitter_delay)

        # ---- Attempt 2 ----
        rc2, stdout2, stderr2, elapsed2 = _run_gate_once(gate_path)
        attempt2 = _attempt_record(rc2, stdout2, stderr2, elapsed2)
        combined2 = stdout2 + stderr2

        if rc2 == 0:
            return {
                "passed": True,
                "detail": f"PASS_WITH_RETRY: {_extract_detail(combined2)}",
                "failure_class": FailureClass.TRANSIENT,
                "attempts": 2,
                "attempt_log": [attempt1, attempt2],
                "retry_delay_s": round(jitter_delay, 3),
                "stdout": stdout2[-500:],
                "stderr": stderr2[-500:],
                "cwd": str(REPO_ROOT),
                "duration_s": round(elapsed + jitter_delay + elapsed2, 3),
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc).isoformat(),
            }
        else:
            lines = combined2.strip().split("\n")
            last = lines[-1] if lines else "unknown failure"
            return {
                "passed": False,
                "detail": f"FAIL (confirmed after retry): {last[:200]}",
                "failure_class": FailureClass.DETERMINISTIC,
                "attempts": 2,
                "attempt_log": [attempt1, attempt2],
                "retry_delay_s": round(jitter_delay, 3),
                "stdout": stdout2[-500:],
                "stderr": stderr2[-500:],
                "cwd": str(REPO_ROOT),
                "duration_s": round(elapsed + jitter_delay + elapsed2, 3),
                "start_time": start_time,
                "end_time": datetime.now(timezone.utc).isoformat(),
            }

    # ---- Deterministic failure (no retry warranted) ----
    lines = combined.strip().split("\n")
    last = lines[-1] if lines else "unknown failure"
    return {
        "passed": False,
        "detail": f"FAIL: {last[:200]}",
        "failure_class": fail_class,
        "attempts": 1,
        "attempt_log": [attempt1],
        "stdout": stdout[-500:],
        "stderr": stderr[-500:],
        "cwd": str(REPO_ROOT),
        "duration_s": elapsed,
        "start_time": start_time,
        "end_time": datetime.now(timezone.utc).isoformat(),
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
    parser = argparse.ArgumentParser(description="SONIA v4.0 Promotion Gate")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "reports" / "audit" / "v4.0-baseline"),
    )
    parser.add_argument(
        "--floor-only", action="store_true",
        help="Run only Class A (inherited floor), skip B+C",
    )
    parser.add_argument(
        "--delta-only", action="store_true",
        help="Run only Class B+C (delta), skip Class A",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_start = datetime.now(timezone.utc).isoformat()
    results = []
    class_a_hold = False  # fail-fast flag
    retried_total = 0

    print("=" * 60)
    print("  SONIA v4.0 Promotion Gate (schema v7.0)")
    print("=" * 60)

    # ---- [1/4] Unit test floor check ----
    if not args.delta_only:
        print(f"\n[1/4] Running unit test floor check (>={INHERITED_UNIT_TEST_FLOOR} required)...")
        passed, failed, test_output, dt = run_unit_tests()
        unit_ok = passed >= INHERITED_UNIT_TEST_FLOOR and failed == 0
        status = "PASS" if unit_ok else "FAIL"
        print(f"  [{status}] Unit tests: {passed} passed, {failed} failed ({dt}s)")
        results.append({
            "gate": "UNIT_TEST_FLOOR",
            "class": "A",
            "category": "test_floor",
            "passed": unit_ok,
            "detail": f"{passed} passed, {failed} failed (floor: {INHERITED_UNIT_TEST_FLOOR})",
            "failure_class": None if unit_ok else FailureClass.DETERMINISTIC,
            "attempts": 1,
            "duration_s": dt,
            "cwd": str(REPO_ROOT),
            "start_time": run_start,
            "end_time": datetime.now(timezone.utc).isoformat(),
        })
        if not unit_ok:
            class_a_hold = True
            print("\n  *** FAIL-FAST: Unit test floor breached. Marking HOLD. ***")
    else:
        passed, failed = INHERITED_UNIT_TEST_FLOOR, 0
        unit_ok = True
        print("\n[1/4] Skipped (--delta-only mode)")

    # ---- [2/4] Class A: Inherited baseline gates (33) ----
    if not args.delta_only:
        total_class_a = CLASS_A_COUNT
        print(f"\n[2/4] Running {total_class_a} Class A (inherited) gates...")
        floor_pass = 0
        floor_fail = 0

        # gates/ directory (24 original)
        for gate_file in CLASS_A_GATES_DIR:
            r = run_gate_script(gate_file, GATE_DIR, always_retry=True)
            r["gate"] = gate_file
            r["class"] = "A"
            r["category"] = "inherited"
            r["source_dir"] = "scripts/gates"
            results.append(r)
            if r["passed"]:
                floor_pass += 1
                if r["attempts"] > 1:
                    retried_total += 1
            else:
                floor_fail += 1
            tag = "PASS" if r["passed"] else "FAIL"
            retry_note = " [RETRIED]" if r["attempts"] > 1 else ""
            print(f"  [{tag}] {gate_file}: {r['detail']} ({r['duration_s']}s){retry_note}")
            if not r["passed"]:
                class_a_hold = True
                print(f"  *** FAIL-FAST: Class A gate {gate_file} failed. ***")

        # release/ directory (4 from v3.8)
        for gate_file in CLASS_A_GATES_RELEASE_DIR:
            r = run_gate_script(gate_file, RELEASE_DIR, always_retry=True)
            r["gate"] = gate_file
            r["class"] = "A"
            r["category"] = "inherited"
            r["source_dir"] = "scripts/release"
            results.append(r)
            if r["passed"]:
                floor_pass += 1
                if r["attempts"] > 1:
                    retried_total += 1
            else:
                floor_fail += 1
            tag = "PASS" if r["passed"] else "FAIL"
            retry_note = " [RETRIED]" if r["attempts"] > 1 else ""
            print(f"  [{tag}] {gate_file}: {r['detail']} ({r['duration_s']}s){retry_note}")
            if not r["passed"]:
                class_a_hold = True

        # v3.9 delta (now inherited as Class A)
        for gate_file, directory, label in CLASS_A_GATES_V39_DELTA:
            search_dir = RELEASE_DIR if directory == "release" else GATE_DIR
            r = run_gate_script(gate_file, search_dir, always_retry=True)
            r["gate"] = gate_file
            r["class"] = "A"
            r["category"] = "inherited"
            r["label"] = label
            r["source_dir"] = f"scripts/{directory}"
            results.append(r)
            if r["passed"]:
                floor_pass += 1
                if r["attempts"] > 1:
                    retried_total += 1
            else:
                floor_fail += 1
            tag = "PASS" if r["passed"] else "FAIL"
            retry_note = " [RETRIED]" if r["attempts"] > 1 else ""
            print(f"  [{tag}] {gate_file} ({label}): {r['detail']} ({r['duration_s']}s){retry_note}")
            if not r["passed"]:
                class_a_hold = True

        floor_ok = floor_fail == 0
        retry_label = f" ({retried_total} retried)" if retried_total else ""
        print(f"\n  Class A floor: {floor_pass}/{total_class_a}"
              f" {'PASS' if floor_ok else 'FAIL'}{retry_label}")
    else:
        floor_pass = CLASS_A_COUNT
        floor_fail = 0
        floor_ok = True
        print(f"\n[2/4] Skipped (--delta-only mode)")

    # ---- [3/4] Class B: v4.0 delta gates ----
    delta_pass = 0
    delta_fail = 0
    if not args.floor_only and CLASS_B_GATES:
        print(f"\n[3/4] Running {CLASS_B_COUNT} Class B (v4.0 delta) gates...")
        if class_a_hold:
            print("  (NOTE: Class A HOLD -- delta results are informational only)")
        for gate_file, directory, label in CLASS_B_GATES:
            search_dir = RELEASE_DIR if directory == "release" else GATE_DIR
            r = run_gate_script(gate_file, search_dir)
            r["gate"] = gate_file
            r["class"] = "B"
            r["category"] = "delta"
            r["label"] = label
            r["source_dir"] = f"scripts/{directory}"
            results.append(r)
            if r["passed"]:
                delta_pass += 1
            else:
                delta_fail += 1
            tag = "PASS" if r["passed"] else "FAIL"
            print(f"  [{tag}] {gate_file} ({label}): {r['detail']} ({r['duration_s']}s)")
    else:
        if args.floor_only:
            print(f"\n[3/4] Skipped (--floor-only mode)")
        elif not CLASS_B_GATES:
            print(f"\n[3/4] No Class B gates wired yet")

    # ---- [4/4] Class C: Cross-cutting gates ----
    cross_pass = 0
    cross_fail = 0
    if not args.floor_only and CLASS_C_GATES:
        print(f"\n[4/4] Running {CLASS_C_COUNT} Class C (cross-cutting) gates...")
        for gate_file, directory, label in CLASS_C_GATES:
            search_dir = RELEASE_DIR if directory == "release" else GATE_DIR
            r = run_gate_script(gate_file, search_dir)
            r["gate"] = gate_file
            r["class"] = "C"
            r["category"] = "cross_cutting"
            r["label"] = label
            r["source_dir"] = f"scripts/{directory}"
            results.append(r)
            if r["passed"]:
                cross_pass += 1
            else:
                cross_fail += 1
            tag = "PASS" if r["passed"] else "FAIL"
            print(f"  [{tag}] {gate_file} ({label}): {r['detail']} ({r['duration_s']}s)")
    else:
        if args.floor_only:
            print(f"\n[4/4] Skipped (--floor-only mode)")
        elif not CLASS_C_GATES:
            print(f"\n[4/4] No Class C gates wired yet")

    # ---- Verdict ----
    # Total counts depend on mode
    if args.delta_only:
        total_pass = delta_pass + cross_pass
        total_count = CLASS_B_COUNT + CLASS_C_COUNT
    elif args.floor_only:
        total_pass = (1 if unit_ok else 0) + floor_pass
        total_count = 1 + CLASS_A_COUNT
    else:
        total_pass = (1 if unit_ok else 0) + floor_pass + delta_pass + cross_pass
        total_count = 1 + CLASS_A_COUNT + CLASS_B_COUNT + CLASS_C_COUNT

    all_green = (unit_ok and floor_ok and delta_fail == 0
                 and cross_fail == 0 and not class_a_hold)

    verdict = "PROMOTE" if all_green else "HOLD"
    hold_reasons = []
    if class_a_hold:
        hold_reasons.append("Class A inherited floor regression")
    if not unit_ok:
        hold_reasons.append(f"unit tests below floor ({passed}/{INHERITED_UNIT_TEST_FLOOR})")
    if delta_fail > 0:
        hold_reasons.append(f"{delta_fail} Class B delta gate(s) failed")
    if cross_fail > 0:
        hold_reasons.append(f"{cross_fail} Class C cross-cutting gate(s) failed")

    run_end = datetime.now(timezone.utc).isoformat()

    report = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "timestamp": run_end,
        "run_start": run_start,
        "run_end": run_end,
        "gates_passed": total_pass,
        "gates_total": total_count,
        "class_a_count": CLASS_A_COUNT,
        "class_b_count": CLASS_B_COUNT,
        "class_c_count": CLASS_C_COUNT,
        "inherited_unit_test_floor": INHERITED_UNIT_TEST_FLOOR,
        "unit_tests_passed": passed,
        "unit_tests_failed": failed,
        "floor_only": args.floor_only,
        "delta_only": args.delta_only,
        "retried_gates": retried_total,
        "fail_fast_triggered": class_a_hold,
        "hold_reasons": hold_reasons,
        "verdict": verdict,
        "telemetry": {
            "total_duration_s": sum(r.get("duration_s", 0) for r in results),
            "gate_count": len(results),
            "retried_count": retried_total,
        },
        "gates": results,
    }

    report_path = output_dir / f"gate-matrix-v40-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 60}")
    print(f"  {total_pass}/{total_count} gates passed -- {verdict}")
    if hold_reasons:
        print(f"  HOLD reasons: {'; '.join(hold_reasons)}")
    if retried_total:
        print(f"  ({retried_total} gate(s) passed with retry)")
    if args.floor_only:
        print(f"  (floor-only mode: Class B+C skipped)")
    if args.delta_only:
        print(f"  (delta-only mode: Class A skipped)")
    print(f"  Report: {report_path}")
    print(f"{'=' * 60}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
