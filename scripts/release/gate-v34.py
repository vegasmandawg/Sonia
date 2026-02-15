"""
SONIA v3.4.0 Promotion Gate (M0: Scaffold)
=====================================================
Inherits the full v3.3 floor (157 tests across G18-G29) and adds v3.4 delta gates.

Usage:
    python gate-v34.py [--output-dir S:\\reports\\gate-v34]
    python gate-v34.py --floor-only   # run only inherited floor

Inherited Floor (v3.3):
 G18. Voice latency budget (4 tests)
 G19. Barge-in replay determinism (20 tests)
 G20. Perception dedupe correctness (15 tests)
 G21. Confirmation storm integrity (8 tests)
 G22. Memory proposal governance (16 tests)
 G23. Memory replay integrity (14 tests)
 G24. Ledger edit governance (16 tests)
 G25. Redaction + provenance slicing (14 tests)
 G26. Restore integrity (13 tests)
 G27. Incident triage automation (13 tests)
 G28. Privacy boundary enforcement (14 tests)
 G29. Zero-frame + confirmation hardening (10 tests)
 Floor total: 157 tests

v3.4 Delta Gates (TBD):
 G30-G35: to be wired as epics are defined
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
EXPECTED_VERSION = "3.4.0-dev"
EXPECTED_BRANCH = "v3.4-dev"

V32_VOICE_DIR = REPO_ROOT / "tests" / "v32_voice"
V32_PERCEPTION_DIR = REPO_ROOT / "tests" / "v32_perception"
V32_MEMORY_DIR = REPO_ROOT / "tests" / "v32_memory_ops"
V33_MEMORY_DIR = REPO_ROOT / "tests" / "v33_memory_ops"
V33_RECOVERY_DIR = REPO_ROOT / "tests" / "v33_recovery"
V33_PERCEPTION_DIR = REPO_ROOT / "tests" / "v33_perception"

FLOOR_GATE_COUNT = 12  # G18-G29
DELTA_GATE_COUNT = 0   # TBD: will be set as epics are defined
TOTAL_GATES = FLOOR_GATE_COUNT + DELTA_GATE_COUNT


def run_pytest(test_path, label):
    """Run pytest on a path, return (passed, failed, output)."""
    cmd = [PYTHON, "-m", "pytest", str(test_path), "-v", "--tb=short"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600)
    output = result.stdout + result.stderr
    passed = output.count(" PASSED")
    failed = output.count(" FAILED")
    if passed == 0:
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
    if failed == 0:
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
    return passed, failed, output


# -- Version Check -----------------------------------------------------------

def gate_version():
    """Version consistency check for v3.4."""
    sys.path.insert(0, str(REPO_ROOT / "services" / "shared"))
    if "version" in sys.modules:
        import importlib
        import version
        importlib.reload(version)
        from version import SONIA_VERSION, SONIA_CONTRACT
    else:
        from version import SONIA_VERSION, SONIA_CONTRACT
    sys.path.pop(0)
    version_ok = SONIA_VERSION == EXPECTED_VERSION
    contract_ok = SONIA_CONTRACT == "v3.0.0"
    return version_ok and contract_ok, f"version={SONIA_VERSION} contract={SONIA_CONTRACT}"


# -- Inherited Floor (v3.3: 157 tests) --------------------------------------

def gate_full_floor():
    """Run entire inherited floor (157 tests) as a single gate."""
    dirs = [
        V32_VOICE_DIR, V32_PERCEPTION_DIR, V32_MEMORY_DIR,
        V33_MEMORY_DIR, V33_RECOVERY_DIR, V33_PERCEPTION_DIR,
    ]
    for d in dirs:
        if not d.exists():
            return False, f"missing dir: {d}"
    cmd = [PYTHON, "-m", "pytest"] + [str(d) for d in dirs] + ["-v", "--tb=short"]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=600)
    output = result.stdout + result.stderr
    passed = output.count(" PASSED")
    failed = output.count(" FAILED")
    if passed == 0:
        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))
    if failed == 0:
        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))
    return failed == 0 and passed >= 157, f"{passed} passed, {failed} failed (floor: 157)"


def gate_voice_latency():
    """G18: Voice latency budget (4 tests)."""
    f = V32_VOICE_DIR / "test_latency_budget_g18.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G18")
    return fl == 0 and p >= 4, f"{p} passed, {fl} failed"


def gate_bargein_replay():
    """G19: Barge-in replay determinism (20 tests)."""
    files = [
        V32_VOICE_DIR / "test_replay_determinism.py",
        V32_VOICE_DIR / "test_bargein_cancel_semantics.py",
        V32_VOICE_DIR / "test_turn_lifecycle.py",
    ]
    for f in files:
        if not f.exists():
            return False, f"missing: {f.name}"
    total_p, total_f = 0, 0
    for f in files:
        p, fl, _ = run_pytest(f, f"G19:{f.stem}")
        total_p += p
        total_f += fl
    return total_f == 0 and total_p >= 20, f"{total_p} passed, {total_f} failed"


def gate_perception_dedupe():
    """G20: Perception dedupe correctness (15 tests)."""
    files = [
        V32_PERCEPTION_DIR / "test_dedupe_correctness.py",
        V32_PERCEPTION_DIR / "test_priority_routing.py",
    ]
    for f in files:
        if not f.exists():
            return False, f"missing: {f.name}"
    total_p, total_f = 0, 0
    for f in files:
        p, fl, _ = run_pytest(f, f"G20:{f.stem}")
        total_p += p
        total_f += fl
    return total_f == 0 and total_p >= 15, f"{total_p} passed, {total_f} failed"


def gate_confirmation_storm():
    """G21: Confirmation storm integrity (8 tests)."""
    f = V32_PERCEPTION_DIR / "test_confirmation_storm_integrity.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G21")
    return fl == 0 and p >= 8, f"{p} passed, {fl} failed"


def gate_memory_proposal():
    """G22: Memory proposal governance (16 tests)."""
    f = V32_MEMORY_DIR / "test_proposal_governance.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G22")
    return fl == 0 and p >= 16, f"{p} passed, {fl} failed"


def gate_memory_replay():
    """G23: Memory replay integrity (14 tests)."""
    f = V32_MEMORY_DIR / "test_replay_determinism.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G23")
    return fl == 0 and p >= 14, f"{p} passed, {fl} failed"


def gate_g24():
    """G24: Ledger edit governance (>=16 tests)."""
    f = V33_MEMORY_DIR / "test_ledger_edit_governance.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G24")
    return fl == 0 and p >= 16, f"{p} passed, {fl} failed"


def gate_g25():
    """G25: Redaction + provenance slicing (>=14 tests)."""
    f = V33_MEMORY_DIR / "test_redaction_provenance.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G25")
    return fl == 0 and p >= 14, f"{p} passed, {fl} failed"


def gate_g26():
    """G26: Restore integrity (>=12 tests)."""
    f = V33_RECOVERY_DIR / "test_restore_integrity.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G26")
    return fl == 0 and p >= 12, f"{p} passed, {fl} failed"


def gate_g27():
    """G27: Incident triage (>=10 tests)."""
    f = V33_RECOVERY_DIR / "test_incident_triage.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G27")
    return fl == 0 and p >= 10, f"{p} passed, {fl} failed"


def gate_g28():
    """G28: Privacy boundary enforcement (>=12 tests)."""
    f = V33_PERCEPTION_DIR / "test_privacy_boundary.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G28")
    return fl == 0 and p >= 12, f"{p} passed, {fl} failed"


def gate_g29():
    """G29: Zero-frame + confirmation hardening (>=10 tests)."""
    f = V33_PERCEPTION_DIR / "test_zero_frame_confirmation.py"
    if not f.exists():
        return False, "test file not found"
    p, fl, _ = run_pytest(f, "G29")
    return fl == 0 and p >= 10, f"{p} passed, {fl} failed"


# -- v3.4 Delta Gates (TBD) -------------------------------------------------

# def gate_g30():
#     """G30: TBD -- wire when Epic A is defined."""
#     pass

# def gate_g31():
#     """G31: TBD -- wire when Epic A is defined."""
#     pass


# -- Runner ----------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SONIA v3.4 Promotion Gate")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "reports" / "gate-v34"))
    parser.add_argument("--floor-only", action="store_true",
                        help="Run only inherited floor, skip v3.4 delta gates")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    gates = [
        ("G00_version", gate_version),
        ("FLOOR_v33_157", gate_full_floor),
        ("G18_voice_latency", gate_voice_latency),
        ("G19_bargein_replay", gate_bargein_replay),
        ("G20_perception_dedupe", gate_perception_dedupe),
        ("G21_confirmation_storm", gate_confirmation_storm),
        ("G22_memory_proposal", gate_memory_proposal),
        ("G23_memory_replay", gate_memory_replay),
        ("G24_ledger_edit", gate_g24),
        ("G25_redaction_provenance", gate_g25),
        ("G26_restore_integrity", gate_g26),
        ("G27_incident_triage", gate_g27),
        ("G28_privacy_boundary", gate_g28),
        ("G29_zero_frame_confirmation", gate_g29),
    ]

    # v3.4 delta gates (add here as epics are wired)
    if not args.floor_only:
        pass  # gates.extend([...])

    results = []
    for name, fn in gates:
        t0 = time.time()
        try:
            passed, detail = fn()
        except Exception as e:
            passed, detail = False, f"ERROR: {e}"
        dt = round(time.time() - t0, 3)
        results.append({
            "gate": name,
            "passed": passed,
            "detail": detail,
            "duration_s": dt,
        })
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}: {detail} ({dt}s)")

    pass_count = sum(1 for r in results if r["passed"])
    total = len(results)
    verdict = "PROMOTE" if pass_count == total else "HOLD"

    report = {
        "schema_version": "4.0",
        "version": EXPECTED_VERSION,
        "branch": EXPECTED_BRANCH,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gates_passed": pass_count,
        "gates_total": total,
        "inherited_floor": 157,
        "delta_gates_wired": DELTA_GATE_COUNT,
        "floor_only": args.floor_only,
        "verdict": verdict,
        "gates": results,
    }

    report_path = output_dir / "gate-report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n{'=' * 50}")
    print(f"  {pass_count}/{total} gates passed -- {verdict}")
    if args.floor_only:
        print(f"  (floor-only mode: v3.4 delta gates skipped)")
    print(f"  Report: {report_path}")

    return 0 if verdict == "PROMOTE" else 1


if __name__ == "__main__":
    sys.exit(main())
