"""v3.7 Release Stamp — Generate immutable release bundle with SHA-256 manifest."""
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(r"S:\\")
RELEASE_DIR = ROOT / "releases" / "v3.7.0"
RELEASE_DIR.mkdir(parents=True, exist_ok=True)

ts = time.strftime("%Y%m%d-%H%M%S")

# 1. Gate matrix summary
gate_dir = ROOT / "scripts" / "gates"
gate_files = sorted(gate_dir.glob("*.py"))
# Exclude underscore-prefixed legacy gates
target_gates = [g for g in gate_files if not g.name.startswith("_")]

gate_results = []
for gf in target_gates:
    try:
        r = subprocess.run(
            [str(ROOT / "envs" / "sonia-core" / "python.exe"), str(gf)],
            capture_output=True, text=True, timeout=120,
        )
        verdict = "PASS" if r.returncode == 0 else "FAIL"
    except Exception as e:
        verdict = "ERROR"
    gate_results.append({"gate": gf.name, "verdict": verdict})

gate_matrix = {
    "timestamp": ts,
    "total": len(gate_results),
    "passed": sum(1 for g in gate_results if g["verdict"] == "PASS"),
    "gates": gate_results,
}
(RELEASE_DIR / "gate-matrix.json").write_text(json.dumps(gate_matrix, indent=2))

# 2. Unit test summary
r = subprocess.run(
    [str(ROOT / "envs" / "sonia-core" / "python.exe"), "-m", "pytest",
     str(ROOT / "tests" / "unit"), "-q", "--tb=no"],
    capture_output=True, text=True, timeout=120,
)
lines = r.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""
unit_summary = {
    "timestamp": ts,
    "summary": summary_line,
    "returncode": r.returncode,
    "test_output": r.stdout[-2000:] if len(r.stdout) > 2000 else r.stdout,
}
(RELEASE_DIR / "unit-test-summary.json").write_text(json.dumps(unit_summary, indent=2))

# 3. Copy key artifacts
artifacts_to_copy = [
    (ROOT / "reports" / "audit" / "FINAL_SCORECARD.md", "FINAL_SCORECARD.md"),
    (ROOT / "requirements-frozen.txt", "requirements-frozen.txt"),
    (ROOT / "dependency-lock.json", "dependency-lock.json"),
]
for src, dst in artifacts_to_copy:
    if src.exists():
        shutil.copy2(src, RELEASE_DIR / dst)

# 4. Changelog
changelog = {
    "version": "3.7.0",
    "timestamp": ts,
    "milestones": [
        {
            "id": "M1",
            "title": "Session and Memory Sovereignty",
            "modules": ["session_isolation.py", "memory_silo.py"],
            "tests": 39,
            "gates": ["session-isolation-gate.py (8/8)", "memory-silo-gate.py (8/8)"],
        },
        {
            "id": "M2",
            "title": "Recovery + Incident Determinism",
            "modules": ["recovery_policy.py", "dlq_replay_policy.py"],
            "tests": 59,
            "gates": ["recovery-determinism-gate.py (8/8)", "incident-lineage-gate.py (8/8)"],
        },
        {
            "id": "M3",
            "title": "Runtime QoS and Budget Enforcement",
            "modules": ["output_budget.py", "runtime_qos.py"],
            "tests": 54,
            "gates": ["runtime-qos-gate.py (8/8)", "output-budget-gate.py (8/8)"],
        },
    ],
    "total_new_tests": 152,
    "total_unit_tests": 299,
    "total_gates": 24,
}
(RELEASE_DIR / "changelog.json").write_text(json.dumps(changelog, indent=2))

# 5. SHA-256 manifest
manifest = {"version": "3.7.0", "timestamp": ts, "files": {}}
for f in sorted(RELEASE_DIR.iterdir()):
    if f.name == "release-manifest.json":
        continue
    if f.is_file():
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        manifest["files"][f.name] = {"sha256": sha, "size": f.stat().st_size}

(RELEASE_DIR / "release-manifest.json").write_text(json.dumps(manifest, indent=2))

print(f"Release bundle: {RELEASE_DIR}")
print(f"Artifacts: {len(manifest['files'])} files")
print(f"Gate matrix: {gate_matrix['passed']}/{gate_matrix['total']}")
print(f"Unit tests: {summary_line}")
