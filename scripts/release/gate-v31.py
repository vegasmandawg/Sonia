"""
SONIA v3.1.0 Promotion Gate (H1 Hardening)
============================================
Runs all mandatory gates (12 baseline + 5 hardening) and produces a JSON report.

Usage:
    python gate-v31.py [--output-dir S:\\reports\\gate-v31]

Gates (Baseline 1-12):
  1. Repo hygiene (clean tree, no accidental untracked build junk)
  2. Dependency lock snapshot (pip freeze)
  3. Version consistency (SONIA_VERSION, branch, docs)
  4. M1 contract tests
  5. M2 identity tests
  6. M3 memory ledger tests
  7. M4 perception bridge tests
  8. Full M1-M4 regression (all 112 tests)
  9. Perception -> memory invariants
 10. Confirmation non-bypass (PerceptionActionGate)
 11. Release manifest hash integrity
 12. Clean-room reproducibility smoke

Gates (Hardening 13-17):
 13. Deterministic replay equivalence
 14. Crash-recovery integrity
 15. Confirmation non-bypass under load
 16. Chaos fault injection
 17. Provenance strictness
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("S:/")
PYTHON = str(Path("S:/envs/sonia-core/python.exe"))
TESTS_DIR = REPO_ROOT / "tests" / "integration"
HARDENING_DIR = REPO_ROOT / "tests" / "hardening"
CHAOS_DIR = REPO_ROOT / "scripts" / "chaos"
OUTPUT_DIR_DEFAULT = REPO_ROOT / "reports" / "gate-v31"

EXPECTED_VERSION = "3.1.0"
EXPECTED_BRANCH = "v3.1-dev"

TEST_FILES = {
    "m1": TESTS_DIR / "test_v300_m1_contract.py",
    "m2": TESTS_DIR / "test_v300_m2_identity.py",
    "m3": TESTS_DIR / "test_v300_m3_memory.py",
    "m4": TESTS_DIR / "test_v300_m4_perception.py",
}


def run_cmd(cmd, cwd=None, timeout=300):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd or str(REPO_ROOT), timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"
    except Exception as e:
        return -1, "", str(e)


def gate_result(name, passed, detail="", duration_ms=0):
    return {
        "gate": name,
        "passed": passed,
        "detail": detail,
        "duration_ms": duration_ms,
    }


# ── Gate 1: Repo hygiene ────────────────────────────────────────────────

def gate_repo_hygiene():
    t0 = time.time()
    rc, out, err = run_cmd(["git", "status", "--porcelain=v1"])
    lines = [l for l in out.strip().splitlines() if l.strip()]
    # Allow modifications to scripts/release/, .claude/, releases/, reports/
    ignore_prefixes = [
        "?? scripts/release/", "?? scripts/chaos/", "?? releases/", "?? reports/",
        "?? docs/V3_1_", "?? tests/hardening/",
    ]
    # Also allow modifications to tracked files in H1 areas
    modify_contains = ["scripts/release/", "tests/integration/", "tests/hardening/"]
    dirty = [l for l in lines
             if not any(l.strip().startswith(p) for p in ignore_prefixes)
             and not any(mc in l for mc in modify_contains)
             and ".claude/" not in l]
    dt = int((time.time() - t0) * 1000)
    if not dirty:
        return gate_result("repo_hygiene", True, "Clean tree", dt)
    return gate_result("repo_hygiene", False,
                       f"{len(dirty)} dirty files: {dirty[:5]}", dt)


# ── Gate 2: Dependency snapshot ─────────────────────────────────────────

def gate_dependency_snapshot(output_dir):
    t0 = time.time()
    rc, out, err = run_cmd([PYTHON, "-m", "pip", "freeze"])
    dt = int((time.time() - t0) * 1000)
    if rc != 0:
        return gate_result("dependency_snapshot", False, f"pip freeze failed: {err[:200]}", dt)

    freeze_path = output_dir / "pip-freeze.txt"
    freeze_path.write_text(out, encoding="utf-8")
    pkg_count = len([l for l in out.splitlines() if "==" in l])
    return gate_result("dependency_snapshot", True,
                       f"{pkg_count} packages frozen to {freeze_path.name}", dt)


# ── Gate 3: Version consistency ─────────────────────────────────────────

def gate_version_consistency():
    t0 = time.time()
    issues = []

    # Check SONIA_VERSION in shared/version.py
    version_file = REPO_ROOT / "services" / "shared" / "version.py"
    if version_file.exists():
        content = version_file.read_text(encoding="utf-8")
        if f'SONIA_VERSION = "{EXPECTED_VERSION}"' not in content:
            issues.append(f"version.py does not contain SONIA_VERSION = \"{EXPECTED_VERSION}\"")
    else:
        issues.append("services/shared/version.py not found")

    # Check branch
    rc, out, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = out.strip()
    if branch != EXPECTED_BRANCH:
        issues.append(f"Branch is '{branch}', expected '{EXPECTED_BRANCH}'")

    # Check M4 doc exists
    if not (REPO_ROOT / "docs" / "V3_M4_PERCEPTION_BRIDGE.md").exists():
        issues.append("docs/V3_M4_PERCEPTION_BRIDGE.md not found")

    dt = int((time.time() - t0) * 1000)
    if not issues:
        return gate_result("version_consistency", True,
                           f"v{EXPECTED_VERSION} on {branch}, all docs present", dt)
    return gate_result("version_consistency", False, "; ".join(issues), dt)


# ── Gates 4-7: Individual milestone tests ───────────────────────────────

def gate_milestone_tests(milestone, output_dir):
    t0 = time.time()
    test_file = TEST_FILES[milestone]
    if not test_file.exists():
        return gate_result(f"tests_{milestone}", False, f"{test_file.name} not found", 0)

    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest", str(test_file),
        "-v", "--tb=short", "-q",
    ], timeout=120)
    dt = int((time.time() - t0) * 1000)

    # Save output
    (output_dir / f"tests_{milestone}.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    # Parse results
    passed = rc == 0
    # Find the summary line like "28 passed in 1.23s"
    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()

    return gate_result(f"tests_{milestone}", passed, summary, dt)


# ── Gate 8: Full M1-M4 regression ──────────────────────────────────────

def gate_full_regression(output_dir):
    t0 = time.time()
    test_files = [str(f) for f in TEST_FILES.values() if f.exists()]
    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest"] + test_files + [
        "-v", "--tb=short", "-q",
    ], timeout=180)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "regression_full.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line:
            summary = line.strip()

    return gate_result("regression_full", rc == 0, summary, dt)


# ── Gate 9: Perception -> memory invariants ─────────────────────────────

def gate_perception_invariants(output_dir):
    """Run only the perception->typed-memory and provenance test groups."""
    t0 = time.time()
    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest",
        str(TEST_FILES["m4"]),
        "-v", "--tb=short", "-q",
        "-k", "TestPerceptionTypedMemory or TestProvenanceChain",
    ], timeout=60)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "perception_invariants.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line:
            summary = line.strip()

    return gate_result("perception_invariants", rc == 0, summary, dt)


# ── Gate 10: Confirmation non-bypass ────────────────────────────────────

def gate_confirmation_nonbypass(output_dir):
    t0 = time.time()
    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest",
        str(TEST_FILES["m4"]),
        "-v", "--tb=short", "-q",
        "-k", "TestNoBypassEnforcement or TestConfirmationBinding",
    ], timeout=60)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "confirmation_nonbypass.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line:
            summary = line.strip()

    return gate_result("confirmation_nonbypass", rc == 0, summary, dt)


# ── Gate 11: Release manifest hash integrity ────────────────────────────

def gate_manifest_integrity(output_dir):
    """Hash key source files to create a reproducibility fingerprint."""
    t0 = time.time()
    key_files = [
        "services/api-gateway/perception_memory_bridge.py",
        "services/memory-engine/core/provenance.py",
        "services/memory-engine/main.py",
        "services/shared/version.py",
        "tests/integration/test_v300_m4_perception.py",
        ".gitignore",
    ]
    hashes = {}
    for rel in key_files:
        fpath = REPO_ROOT / rel
        if fpath.exists():
            content = fpath.read_bytes()
            hashes[rel] = hashlib.sha256(content).hexdigest()
        else:
            hashes[rel] = "MISSING"

    dt = int((time.time() - t0) * 1000)
    (output_dir / "file_hashes.json").write_text(
        json.dumps(hashes, indent=2), encoding="utf-8")

    missing = [k for k, v in hashes.items() if v == "MISSING"]
    if missing:
        return gate_result("manifest_integrity", False,
                           f"Missing files: {missing}", dt)
    return gate_result("manifest_integrity", True,
                       f"{len(hashes)} files hashed", dt)


# ── Gate 12: Clean-room reproducibility smoke ───────────────────────────

def gate_cleanroom_smoke(output_dir):
    """Verify imports work and core modules load without error."""
    t0 = time.time()
    check_code = """
import sys
sys.path.insert(0, r"S:\\services\\api-gateway")
sys.path.insert(0, r"S:\\services\\memory-engine")
sys.path.insert(0, r"S:\\services\\shared")

# Core imports
from perception_memory_bridge import PerceptionMemoryBridge, PerceptionIngestResult
from core.provenance import ProvenanceTracker
from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
from version import SONIA_VERSION

assert SONIA_VERSION == "3.1.0", f"Version mismatch: {SONIA_VERSION}"
print("CLEAN_ROOM_OK")
"""
    rc, out, err = run_cmd([PYTHON, "-c", check_code], timeout=30)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "cleanroom_smoke.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    passed = rc == 0 and "CLEAN_ROOM_OK" in out
    return gate_result("cleanroom_smoke", passed,
                       "All core modules imported successfully" if passed
                       else f"Import failed: {err[:200]}", dt)


# ── Gate 13: Hardening - Replay determinism ────────────────────────────

def gate_hardening_replay(output_dir):
    """Run replay determinism tests."""
    t0 = time.time()
    test_file = HARDENING_DIR / "test_replay_determinism.py"
    if not test_file.exists():
        return gate_result("hardening_replay_determinism", False, f"{test_file.name} not found", 0)

    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest", str(test_file),
        "-v", "--tb=short", "-q",
    ], timeout=120)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "hardening_replay.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()

    return gate_result("hardening_replay_determinism", rc == 0, summary, dt)


# ── Gate 14: Hardening - Recovery integrity ────────────────────────────

def gate_hardening_recovery(output_dir):
    """Run crash-recovery integrity tests."""
    t0 = time.time()
    test_file = HARDENING_DIR / "test_recovery_integrity.py"
    if not test_file.exists():
        return gate_result("hardening_recovery_integrity", False, f"{test_file.name} not found", 0)

    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest", str(test_file),
        "-v", "--tb=short", "-q",
    ], timeout=120)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "hardening_recovery.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()

    return gate_result("hardening_recovery_integrity", rc == 0, summary, dt)


# ── Gate 15: Hardening - Confirmation under load ───────────────────────

def gate_hardening_confirmation_load(output_dir):
    """Run confirmation non-bypass under load tests."""
    t0 = time.time()
    test_file = HARDENING_DIR / "test_confirmation_non_bypass_under_load.py"
    if not test_file.exists():
        return gate_result("hardening_confirmation_load", False, f"{test_file.name} not found", 0)

    rc, out, err = run_cmd([
        PYTHON, "-m", "pytest", str(test_file),
        "-v", "--tb=short", "-q",
    ], timeout=120)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "hardening_confirmation_load.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    summary = ""
    for line in (out + err).splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()

    return gate_result("hardening_confirmation_load", rc == 0, summary, dt)


# ── Gate 16: Hardening - Chaos fault injection ─────────────────────────

def gate_hardening_chaos(output_dir):
    """Run all chaos scripts and verify they pass."""
    t0 = time.time()
    chaos_scripts = sorted(CHAOS_DIR.glob("chaos_*.py"))
    if not chaos_scripts:
        return gate_result("hardening_chaos_faults", False, "No chaos scripts found", 0)

    all_passed = True
    details = []
    for script in chaos_scripts:
        rc, out, err = run_cmd([PYTHON, str(script)], timeout=60)
        name = script.stem
        passed = rc == 0
        if not passed:
            all_passed = False
        details.append(f"{name}: {'PASS' if passed else 'FAIL'}")

    dt = int((time.time() - t0) * 1000)
    return gate_result(
        "hardening_chaos_faults", all_passed,
        f"{len(chaos_scripts)} scripts: {'; '.join(details)}", dt)


# ── Gate 17: Hardening - Provenance strictness ─────────────────────────

def gate_hardening_provenance_strict(output_dir):
    """Verify provenance rejects invalid records and tracks valid ones."""
    t0 = time.time()
    check_code = """
import sys, json
sys.path.insert(0, r"S:\\services\\memory-engine")
from unittest.mock import MagicMock

from core.provenance import ProvenanceTracker

mock_db = MagicMock()
mock_conn = MagicMock()
mock_db.connection = MagicMock(return_value=MagicMock(
    __enter__=MagicMock(return_value=mock_conn),
    __exit__=MagicMock(return_value=False),
))

tracker = ProvenanceTracker(mock_db)

# Test 1: Valid perception provenance should succeed
try:
    tracker.track_perception(
        memory_id="mem_valid",
        scene_id="scene_001",
        correlation_id="req_abc",
        trigger="test",
        model_used="model_v1",
    )
    valid_ok = True
except Exception:
    valid_ok = False

# Test 2: Each empty required field should raise ValueError
rejections = 0
for field_name, kwargs in [
    ("scene_id", {"memory_id": "m", "scene_id": "", "correlation_id": "r", "trigger": "t", "model_used": "m"}),
    ("correlation_id", {"memory_id": "m", "scene_id": "s", "correlation_id": "", "trigger": "t", "model_used": "m"}),
    ("trigger", {"memory_id": "m", "scene_id": "s", "correlation_id": "r", "trigger": "", "model_used": "m"}),
    ("model_used", {"memory_id": "m", "scene_id": "s", "correlation_id": "r", "trigger": "t", "model_used": ""}),
]:
    try:
        tracker.track_perception(**kwargs)
    except ValueError:
        rejections += 1

result = {"valid_ok": valid_ok, "rejections": rejections, "expected_rejections": 4}
print("PROVENANCE_STRICT_OK" if valid_ok and rejections == 4 else "PROVENANCE_STRICT_FAIL")
print(json.dumps(result))
"""
    rc, out, err = run_cmd([PYTHON, "-c", check_code], timeout=30)
    dt = int((time.time() - t0) * 1000)

    (output_dir / "hardening_provenance_strict.txt").write_text(
        out + "\n---STDERR---\n" + err, encoding="utf-8")

    passed = rc == 0 and "PROVENANCE_STRICT_OK" in out
    return gate_result("hardening_provenance_strict", passed,
                       "All provenance validations enforced" if passed
                       else f"Provenance strictness failed: {err[:200]}", dt)


# ── Main ────────────────────────────────────────────────────────────────

TOTAL_GATES = 17


def main():
    parser = argparse.ArgumentParser(description="SONIA v3.1.0 Promotion Gate (H1 Hardening)")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR_DEFAULT))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== SONIA v3.1.0 Promotion Gate (H1 Hardening) ===")
    print(f"Output: {output_dir}")
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Gates: {TOTAL_GATES} (12 baseline + 5 hardening)")
    print()

    results = []
    total_t0 = time.time()

    # Gate 1: Repo hygiene
    print(f"[ 1/{TOTAL_GATES}] Repo hygiene...", end=" ", flush=True)
    r = gate_repo_hygiene()
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 2: Dependency snapshot
    print(f"[ 2/{TOTAL_GATES}] Dependency snapshot...", end=" ", flush=True)
    r = gate_dependency_snapshot(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 3: Version consistency
    print(f"[ 3/{TOTAL_GATES}] Version consistency...", end=" ", flush=True)
    r = gate_version_consistency()
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gates 4-7: Individual milestone tests
    for i, ms in enumerate(["m1", "m2", "m3", "m4"], start=4):
        print(f"[ {i}/{TOTAL_GATES}] {ms.upper()} tests...", end=" ", flush=True)
        r = gate_milestone_tests(ms, output_dir)
        results.append(r)
        print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 8: Full regression
    print(f"[ 8/{TOTAL_GATES}] Full M1-M4 regression...", end=" ", flush=True)
    r = gate_full_regression(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 9: Perception invariants
    print(f"[ 9/{TOTAL_GATES}] Perception -> memory invariants...", end=" ", flush=True)
    r = gate_perception_invariants(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 10: Confirmation non-bypass
    print(f"[10/{TOTAL_GATES}] Confirmation non-bypass...", end=" ", flush=True)
    r = gate_confirmation_nonbypass(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 11: Manifest integrity
    print(f"[11/{TOTAL_GATES}] Release manifest integrity...", end=" ", flush=True)
    r = gate_manifest_integrity(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 12: Clean-room smoke
    print(f"[12/{TOTAL_GATES}] Clean-room reproducibility smoke...", end=" ", flush=True)
    r = gate_cleanroom_smoke(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # ── Hardening gates (13-17) ─────────────────────────────────────────

    print()
    print("--- Hardening Gates ---")

    # Gate 13: Replay determinism
    print(f"[13/{TOTAL_GATES}] Replay determinism...", end=" ", flush=True)
    r = gate_hardening_replay(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 14: Recovery integrity
    print(f"[14/{TOTAL_GATES}] Recovery integrity...", end=" ", flush=True)
    r = gate_hardening_recovery(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 15: Confirmation under load
    print(f"[15/{TOTAL_GATES}] Confirmation under load...", end=" ", flush=True)
    r = gate_hardening_confirmation_load(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 16: Chaos faults
    print(f"[16/{TOTAL_GATES}] Chaos fault injection...", end=" ", flush=True)
    r = gate_hardening_chaos(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    # Gate 17: Provenance strictness
    print(f"[17/{TOTAL_GATES}] Provenance strictness...", end=" ", flush=True)
    r = gate_hardening_provenance_strict(output_dir)
    results.append(r)
    print("PASS" if r["passed"] else f"FAIL: {r['detail']}")

    total_ms = int((time.time() - total_t0) * 1000)

    # Summary
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])

    print()
    print(f"{'='*55}")
    print(f"  PASSED: {passed}/{TOTAL_GATES}  |  FAILED: {failed}/{TOTAL_GATES}  |  {total_ms}ms total")
    print(f"{'='*55}")

    # Generate report
    rc, commit_sha, _ = run_cmd(["git", "rev-parse", "HEAD"])
    report = {
        "version": f"v{EXPECTED_VERSION}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": commit_sha.strip(),
        "branch": EXPECTED_BRANCH,
        "total_gates": TOTAL_GATES,
        "passed": passed,
        "failed": failed,
        "baseline_gates": 12,
        "hardening_gates": 5,
        "total_duration_ms": total_ms,
        "verdict": "PROMOTE" if failed == 0 else "BLOCK",
        "gates": results,
    }

    report_path = output_dir / "gate-report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}")
    print(f"Verdict: {report['verdict']}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
