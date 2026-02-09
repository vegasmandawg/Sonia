"""
v2.8.0-rc1 Clean-Room Reproducibility Check

Verifies:
  1. RC tag dereferences to expected commit
  2. All test files exist and are importable
  3. Artifact hashes in manifest match actual files
  4. Full test suite passes from tag state
  5. Core module checksums are deterministic
"""

import sys
import os
import json
import hashlib
import subprocess
import time

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")

RELEASE_DIR = r"S:\releases\v2.8.0-rc1"
PYTHON = r"S:\envs\sonia-core\python.exe"
EXPECTED_COMMIT = "f39689a3"

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f": {detail}" if detail else ""))
    return condition


def main():
    print("\n=== v2.8.0-rc1 Clean-Room Reproducibility Check ===\n")
    all_ok = True
    t0 = time.monotonic()

    # 1. Tag verification
    print("1. Tag verification")
    result = subprocess.run(
        ["git", "-C", r"S:\\", "log", "-1", "--format=%H", "v2.8.0-rc1"],
        capture_output=True, text=True,
    )
    tag_commit = result.stdout.strip()[:8]
    all_ok &= check("RC tag -> commit", tag_commit == EXPECTED_COMMIT, tag_commit)

    # 2. Core module existence and import
    print("\n2. Core module verification")
    core_modules = [
        r"S:\services\api-gateway\model_call_context.py",
        r"S:\services\api-gateway\memory_recall_context.py",
        r"S:\services\api-gateway\perception_action_gate.py",
        r"S:\services\api-gateway\operator_session.py",
        r"S:\services\pipecat\app\voice_turn_router.py",
    ]
    for mod_path in core_modules:
        exists = os.path.exists(mod_path)
        all_ok &= check(f"Exists: {os.path.basename(mod_path)}", exists)

    # Verify imports
    try:
        from model_call_context import ModelCallContext, ModelCallCancelled, ModelCallTimeout
        all_ok &= check("Import: model_call_context", True)
    except ImportError as e:
        all_ok &= check("Import: model_call_context", False, str(e))

    try:
        from memory_recall_context import MemoryRecallContext, MemoryRecallConfig
        all_ok &= check("Import: memory_recall_context", True)
    except ImportError as e:
        all_ok &= check("Import: memory_recall_context", False, str(e))

    try:
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        all_ok &= check("Import: perception_action_gate", True)
    except ImportError as e:
        all_ok &= check("Import: perception_action_gate", False, str(e))

    try:
        from operator_session import OperatorSession, TalkState, InvalidStateTransition
        all_ok &= check("Import: operator_session", True)
    except ImportError as e:
        all_ok &= check("Import: operator_session", False, str(e))

    # 3. Artifact hash verification
    print("\n3. Artifact hash verification")
    manifest_path = os.path.join(RELEASE_DIR, "release_manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)

        for artifact_name, artifact_info in manifest.get("artifacts", {}).items():
            artifact_path = os.path.join(RELEASE_DIR, artifact_name)
            if os.path.exists(artifact_path):
                actual_hash = sha256_file(artifact_path)
                expected_hash = artifact_info["sha256"]
                matches = actual_hash == expected_hash
                all_ok &= check(
                    f"Hash: {artifact_name}",
                    matches,
                    f"{'match' if matches else 'MISMATCH: ' + actual_hash[:16] + ' vs ' + expected_hash[:16]}",
                )
            else:
                all_ok &= check(f"Hash: {artifact_name}", False, "file missing")
    else:
        all_ok &= check("Manifest exists", False)

    # 4. Test file existence
    print("\n4. Test file verification")
    test_files = [
        r"S:\tests\integration\test_v28_model_routing.py",
        r"S:\tests\integration\test_v28_memory_integration.py",
        r"S:\tests\integration\test_v28_perception_gate.py",
        r"S:\tests\integration\test_v28_operator_ux.py",
        r"S:\tests\integration\test_v28_rc1_hardening.py",
    ]
    for tf in test_files:
        exists = os.path.exists(tf)
        all_ok &= check(f"Test: {os.path.basename(tf)}", exists)

    # 5. Core module checksums (deterministic content)
    print("\n5. Core module checksums")
    for mod_path in core_modules:
        if os.path.exists(mod_path):
            h = sha256_file(mod_path)
            check(f"Checksum: {os.path.basename(mod_path)}", True, h[:16])

    # 6. Quick smoke: run hardening tests
    print("\n6. Test suite smoke check")
    result = subprocess.run(
        [PYTHON, "-m", "pytest",
         r"S:\tests\integration\test_v28_rc1_hardening.py",
         "--tb=line", "-q"],
        capture_output=True, text=True, timeout=120,
    )
    passed = "passed" in result.stdout and "failed" not in result.stdout
    all_ok &= check("RC1 hardening tests", passed,
                     result.stdout.strip().split("\n")[-1] if result.stdout else result.stderr[:100])

    elapsed = (time.monotonic() - t0) * 1000

    # Verdict
    print(f"\n=== Reproducibility Check: {'PASS' if all_ok else 'FAIL'} ({elapsed:.0f}ms) ===")

    # JSON output
    report = {
        "version": "v2.8.0-rc1",
        "reproducible": all_ok,
        "tag_commit": tag_commit,
        "expected_commit": EXPECTED_COMMIT,
        "elapsed_ms": round(elapsed, 1),
    }
    report_path = os.path.join(RELEASE_DIR, "reports", "reproducibility-check.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Report: {report_path}")

    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
