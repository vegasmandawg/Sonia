"""
SONIA v4.2.0 Promotion Gate
============================
Schema v9.0 -- three gate classes (A/B/C), retry classifier, per-gate telemetry.

Inherits the full v4.1 floor (41 gates, 753 unit tests) and adds v4.2 delta gates.

FAIL-FAST: Any Class-A gate failure immediately marks HOLD.

Gate Classes:
  A -- Inherited baseline (41 from v4.1.0): fail-fast, always_retry
  B -- v4.2 delta gates (epic-owned): per-epic additions
  C -- Cross-cutting gates (evidence integrity): structural checks

Usage:
    python gate-v42.py [--output-dir DIR]
    python gate-v42.py --floor-only    # Class A only
    python gate-v42.py --delta-only    # Class B + C only

Hardening:
  - One retry for ambiguous failures (empty output, subprocess noise)
  - Persists stdout/stderr + cwd + elapsed per gate
  - Classifies failures: deterministic_fail | transient_fail | timeout | not_found
  - PASS_WITH_RETRY outcome with evidence trail
  - Per-gate telemetry: start_time, end_time, duration_s, attempts
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

SCHEMA_VERSION = "9.0"
VERSION = "4.2.0-dev"

# ---- Class A: Inherited baseline gates (41 from v4.1.0) ---------------------
# 24 original (v3.7) + 4 release-dir + 4 delta (v3.9) + 3 delta (v4.0) + 1 evidence (v4.0)
# + 3 delta (v4.1) + 1 evidence (v4.1) = 40 gate scripts + 1 test floor = 41

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

CLASS_A_GATES_V40_DELTA = [
    ("v40-epic1-gate.py", "gates", "v4.0 E1: Session & Memory Governance"),
    ("v40-epic2-gate.py", "gates", "v4.0 E2: Recovery, Incident Lineage, Determinism"),
    ("v40-epic3-gate.py", "gates", "v4.0 E3: Runtime QoS, Contract Fidelity, Release"),
]

CLASS_A_GATES_V40_EVIDENCE = [
    ("v40-evidence-integrity-gate.py", "gates", "v4.0 Evidence Integrity"),
]

CLASS_A_GATES_V41_DELTA = [
    ("v41-epic1-provenance-gate.py", "gates", "v4.1 E1: Governance Provenance Deepening"),
    ("v41-epic2-chaos-recovery-gate.py", "gates", "v4.1 E2: Fault/Recovery Determinism Under Stress"),
    ("v41-epic3-repro-gate.py", "gates", "v4.1 E3: Reproducible Release + Cleanroom Parity"),
]

CLASS_A_GATES_V41_EVIDENCE = [
    ("v41-evidence-integrity-gate.py", "gates", "v4.1 Evidence Integrity"),
]

CLASS_A_COUNT = (len(CLASS_A_GATES_DIR) + len(CLASS_A_GATES_RELEASE_DIR)
                 + len(CLASS_A_GATES_V39_DELTA) + len(CLASS_A_GATES_V40_DELTA)
                 + len(CLASS_A_GATES_V40_EVIDENCE)
                 + len(CLASS_A_GATES_V41_DELTA) + len(CLASS_A_GATES_V41_EVIDENCE))
INHERITED_UNIT_TEST_FLOOR = 753

# ---- Class B: v4.2 delta gates (epic-owned) ---------------------------------

CLASS_B_GATES = [
    ("v42-epic1-gate.py", "gates", "E1: TBD"),
    ("v42-epic2-gate.py", "gates", "E2: TBD"),
    ("v42-epic3-gate.py", "gates", "E3: TBD"),
]

CLASS_B_COUNT = len(CLASS_B_GATES)

# ---- Class C: Cross-cutting gates -------------------------------------------

CLASS_C_GATES = [
    ("v42-evidence-integrity-gate.py", "gates", "Evidence Integrity"),
]

CLASS_C_COUNT = len(CLASS_C_GATES)

TOTAL_GATES = CLASS_A_COUNT + CLASS_B_COUNT + CLASS_C_COUNT  # + 1 for test floor


# ---- Retry classifier -------------------------------------------------------

class FailureClass:
    DETERMINISTIC = "deterministic_fail"
    TRANSIENT = "transient_fail"
    TIMEOUT = "timeout"
    NOT_FOUND = "not_found"


def _classify_failure(returncode, stdout, stderr, always_retry=False):
    combined = (stdout or "") + (stderr or "")
    if returncode == -1:
        return FailureClass.TIMEOUT, False
    if always_retry and returncode != 0:
        return FailureClass.TRANSIENT, True
    if returncode != 0:
        if len(combined.strip()) < 20:
            return FailureClass.TRANSIENT, True
        if "DeprecatedSince" in stderr and "FAIL" not in stdout:
            return FailureClass.TRANSIENT, True
        if "timed out" in combined.lower() and "FAIL" not in stdout:
            return FailureClass.TRANSIENT, True
    return FailureClass.DETERMINISTIC, False


RETRY_BASE_DELAY = 2.0
RETRY_JITTER_MAX = 1.5


def _backoff_delay():
    return RETRY_BASE_DELAY + random.uniform(0, RETRY_JITTER_MAX)


def _run_gate_once(gate_path):
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
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*checks?\s*PASS", combined)
    return f"{m.group(1)}/{m.group(2)} checks PASS" if m else "PASS"


def _attempt_record(rc, stdout, stderr, elapsed):
    return {
        "returncode": rc,
        "stdout_tail": (stdout or "")[-400:],
        "stderr_tail": (stderr or "")[-400:],
        "elapsed_s": elapsed,
    }


def run_gate_script(gate_file, search_dir, always_retry=False):
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

    fail_class, should_retry = _classify_failure(rc, stdout, stderr, always_retry)

    if should_retry:
        jitter_delay = _backoff_delay()
        time.sleep(jitter_delay)
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
    cmd = [PYTHON, "-m", "pytest", str(UNIT_TEST_DIR), "-v", "--tb=short"]
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(REPO_ROOT), timeout=600,
        )
        elapsed = round(time.time() - t0, 3)
        output = result.stdout + result.stderr
        passed = failed = 0
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
        return passed, failed, output, elapsed
    except subprocess.TimeoutExpired:
        return 0, -1, "TIMEOUT", round(time.time() - t0, 3)
    except Exception as e:
        return 0, -1, str(e), round(time.time() - t0, 3)


# ---- Main orchestration -----------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SONIA v4.2 Promotion Gate")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "reports" / "audit" / "v4.2-baseline"),
    )
    parser.add_argument("--floor-only", action="store_true")
    parser.add_argument("--delta-only", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_start = datetime.now(timezone.utc).isoformat()
    results = []
    class_a_hold = False
    retried_total = 0

    print("=" * 60)
    print("  SONIA v4.2 Promotion Gate (schema v9.0)")
    print("=" * 60)

    # ---- [1/4] Unit test floor ----
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

    # ---- [2/4] Class A: Inherited baseline gates ----
    def _run_class_a_list(gate_list, search_dir, is_tuple=False):
        nonlocal class_a_hold, retried_total
        p = f = 0
        for item in gate_list:
            if is_tuple:
                gate_file, directory, label = item
                sd = RELEASE_DIR if directory == "release" else GATE_DIR
            else:
                gate_file = item
                sd = search_dir
                label = None
            r = run_gate_script(gate_file, sd, always_retry=True)
            r["gate"] = gate_file
            r["class"] = "A"
            r["category"] = "inherited"
            if label:
                r["label"] = label
            results.append(r)
            if r["passed"]:
                p += 1
                if r["attempts"] > 1:
                    retried_total += 1
            else:
                f += 1
            tag = "PASS" if r["passed"] else "FAIL"
            retry_note = " [RETRIED]" if r["attempts"] > 1 else ""
            lbl = f" ({label})" if label else ""
            print(f"  [{tag}] {gate_file}{lbl}: {r['detail']} ({r['duration_s']}s){retry_note}")
            if not r["passed"]:
                class_a_hold = True
                print(f"  *** FAIL-FAST: Class A gate {gate_file} failed. ***")
        return p, f

    if not args.delta_only:
        print(f"\n[2/4] Running {CLASS_A_COUNT} Class A (inherited) gates...")
        fp, ff = 0, 0
        p, f = _run_class_a_list(CLASS_A_GATES_DIR, GATE_DIR)
        fp += p; ff += f
        p, f = _run_class_a_list(CLASS_A_GATES_RELEASE_DIR, RELEASE_DIR)
        fp += p; ff += f
        p, f = _run_class_a_list(CLASS_A_GATES_V39_DELTA, None, is_tuple=True)
        fp += p; ff += f
        p, f = _run_class_a_list(CLASS_A_GATES_V40_DELTA, None, is_tuple=True)
        fp += p; ff += f
        p, f = _run_class_a_list(CLASS_A_GATES_V40_EVIDENCE, None, is_tuple=True)
        fp += p; ff += f
        p, f = _run_class_a_list(CLASS_A_GATES_V41_DELTA, None, is_tuple=True)
        fp += p; ff += f
        p, f = _run_class_a_list(CLASS_A_GATES_V41_EVIDENCE, None, is_tuple=True)
        fp += p; ff += f

        floor_ok = ff == 0
        retry_label = f" ({retried_total} retried)" if retried_total else ""
        print(f"\n  Class A floor: {fp}/{CLASS_A_COUNT}"
              f" {'PASS' if floor_ok else 'FAIL'}{retry_label}")
    else:
        fp = CLASS_A_COUNT
        ff = 0
        floor_ok = True
        print(f"\n[2/4] Skipped (--delta-only mode)")

    # ---- [3/4] Class B: v4.2 delta gates ----
    delta_pass = delta_fail = 0
    if not args.floor_only and CLASS_B_GATES:
        print(f"\n[3/4] Running {CLASS_B_COUNT} Class B (v4.2 delta) gates...")
        if class_a_hold:
            print("  (NOTE: Class A HOLD -- delta results are informational only)")
        for gate_file, directory, label in CLASS_B_GATES:
            search_dir = RELEASE_DIR if directory == "release" else GATE_DIR
            r = run_gate_script(gate_file, search_dir)
            r["gate"] = gate_file
            r["class"] = "B"
            r["category"] = "delta"
            r["label"] = label
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
    cross_pass = cross_fail = 0
    if not args.floor_only and CLASS_C_GATES:
        print(f"\n[4/4] Running {CLASS_C_COUNT} Class C (cross-cutting) gates...")
        for gate_file, directory, label in CLASS_C_GATES:
            search_dir = RELEASE_DIR if directory == "release" else GATE_DIR
            r = run_gate_script(gate_file, search_dir)
            r["gate"] = gate_file
            r["class"] = "C"
            r["category"] = "cross_cutting"
            r["label"] = label
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
    if args.delta_only:
        total_pass = delta_pass + cross_pass
        total_count = CLASS_B_COUNT + CLASS_C_COUNT
    elif args.floor_only:
        total_pass = (1 if unit_ok else 0) + fp
        total_count = 1 + CLASS_A_COUNT
    else:
        total_pass = (1 if unit_ok else 0) + fp + delta_pass + cross_pass
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

    report_path = output_dir / f"gate-matrix-v42-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'=' * 60}")
    print(f"  {total_pass}/{total_count} gates passed -- {verdict}")
    print(f"  Report: {report_path}")
    print(f"{'=' * 60}")

    sys.exit(0 if all_green else 1)


if __name__ == "__main__":
    main()
