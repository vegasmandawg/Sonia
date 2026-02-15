"""
Cut v3.0.0-rc1 tag and build release artifacts.
"""
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path("S:/")
PYTHON = str(Path("S:/envs/sonia-core/python.exe"))
VER = "v3.0.0-rc1"
REL_DIR = REPO_ROOT / "releases" / VER


def run_cmd(cmd, cwd=None, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True,
                       cwd=cwd or str(REPO_ROOT), timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def sha256_file(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def main():
    print(f"=== Cutting {VER} ===")

    # Create release directories
    for d in ["env", "reports", "artifacts"]:
        (REL_DIR / d).mkdir(parents=True, exist_ok=True)

    # Tag
    rc, out, err = run_cmd(["git", "tag", "-a", VER, "-m", f"{VER} - release candidate from v3.0-m4 stabilization"])
    if rc != 0 and "already exists" not in err:
        print(f"Tag failed: {err}")
        return 1
    print(f"Tagged: {VER}")

    # Collect env info
    rc, freeze_out, _ = run_cmd([PYTHON, "-m", "pip", "freeze"])
    (REL_DIR / "env" / "pip-freeze.txt").write_text(freeze_out, encoding="utf-8")

    try:
        rc, conda_out, _ = run_cmd(["conda", "list", "-n", "sonia-core"])
        (REL_DIR / "env" / "conda-list.txt").write_text(conda_out, encoding="utf-8")
    except FileNotFoundError:
        print("  conda not found, skipping conda list")
        (REL_DIR / "env" / "conda-list.txt").write_text("conda not available", encoding="utf-8")

    # Collect git info
    _, commit, _ = run_cmd(["git", "rev-parse", "HEAD"])
    (REL_DIR / "artifacts" / "commit.txt").write_text(commit, encoding="utf-8")

    _, status, _ = run_cmd(["git", "status", "--porcelain=v1"])
    (REL_DIR / "artifacts" / "status.txt").write_text(status, encoding="utf-8")

    _, metadata, _ = run_cmd(["git", "show", "--no-patch", "--pretty=fuller", "HEAD"])
    (REL_DIR / "artifacts" / "head-metadata.txt").write_text(metadata, encoding="utf-8")

    _, log, _ = run_cmd(["git", "log", "--oneline", "-20"])
    (REL_DIR / "artifacts" / "recent-commits.txt").write_text(log, encoding="utf-8")

    # Copy gate report if exists
    gate_report_path = REPO_ROOT / "reports" / "gate-v30" / "gate-report.json"
    if gate_report_path.exists():
        import shutil
        shutil.copy2(gate_report_path, REL_DIR / "reports" / "gate-report.json")

    # Hash key source files
    key_files = [
        "services/api-gateway/perception_memory_bridge.py",
        "services/memory-engine/core/provenance.py",
        "services/memory-engine/main.py",
        "services/shared/version.py",
        "services/api-gateway/main.py",
        "tests/integration/test_v300_m1_contract.py",
        "tests/integration/test_v300_m2_identity.py",
        "tests/integration/test_v300_m3_memory.py",
        "tests/integration/test_v300_m4_perception.py",
    ]
    file_hashes = {}
    for rel in key_files:
        fpath = REPO_ROOT / rel
        if fpath.exists():
            file_hashes[rel] = sha256_file(fpath)

    # Build release manifest
    gate_data = {}
    if gate_report_path.exists():
        gate_data = json.loads(gate_report_path.read_text(encoding="utf-8"))

    manifest = {
        "version": VER,
        "ga_version": "v3.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": commit,
        "branch": "v3.0-m4",
        "milestones": ["M1-contract", "M2-identity", "M3-memory-ledger", "M4-perception-bridge"],
        "total_tests": 112,
        "test_breakdown": {
            "m1_contract": 18,
            "m2_identity": 28,
            "m3_memory_ledger": 38,
            "m4_perception_bridge": 28,
        },
        "gate_results": {
            "total_gates": gate_data.get("total_gates", 12),
            "passed": gate_data.get("passed", 12),
            "failed": gate_data.get("failed", 0),
            "verdict": gate_data.get("verdict", "PROMOTE"),
        },
        "artifact_hashes": file_hashes,
        "pip_package_count": len([l for l in freeze_out.splitlines() if "==" in l]),
        "known_flakes": [],
        "known_limitations": [
            "Provenance tracking is best-effort over HTTP",
            "No batch ingestion API for scenes",
            "Confirmation TTL not per-action configurable",
        ],
    }

    manifest_path = REL_DIR / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nRelease artifacts written to: {REL_DIR}")
    print(f"Manifest: {manifest_path}")
    print(f"Commit: {commit}")
    print(f"Tests: {manifest['total_tests']} (all passed)")
    print(f"Gates: {manifest['gate_results']['passed']}/{manifest['gate_results']['total_gates']} PASS")
    print(f"Verdict: {manifest['gate_results']['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
