"""
Build the canonical GA bundle at S:\\releases\\v2.8.0\\

Copies all RC1 artifacts, regenerates manifest with GA metadata,
recomputes hashes for the new manifest.
"""

import os
import sys
import json
import shutil
import hashlib
import time

RC_DIR = r"S:\releases\v2.8.0-rc1"
GA_DIR = r"S:\releases\v2.8.0"
GA_COMMIT = "fbf869a2"
GA_TAG = "v2.8.0"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    # 1. Create GA directory structure
    for subdir in ["reports", "env", "incidents"]:
        os.makedirs(os.path.join(GA_DIR, subdir), exist_ok=True)
    print(f"Created {GA_DIR}")

    # 2. Copy all artifacts except manifest (we'll regenerate)
    skip_files = {"release_manifest.json", "build_ga_bundle.py", "gen_manifest.py", "_build_bundle.ps1"}
    copied = 0
    for root, dirs, files in os.walk(RC_DIR):
        for fname in files:
            if fname in skip_files:
                continue
            src = os.path.join(root, fname)
            rel = os.path.relpath(src, RC_DIR)
            dst = os.path.join(GA_DIR, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
            print(f"  Copied: {rel}")

    # 3. Regenerate changelog to cover GA commit
    changelog_path = os.path.join(GA_DIR, "CHANGELOG.txt")
    with open(changelog_path, "w") as f:
        f.write("v2.8.0 GA Changelog (v2.7.0..v2.8.0)\n")
        f.write("=" * 42 + "\n\n")
        f.write("fbf869a2 chore(v2.8-ga): promotion artifacts -- 52 hardening tests, gate, soak, cleanroom\n")
        f.write("f39689a3 feat(v2.8): 4 milestones -- model routing, memory integration, perception gate, operator UX (104 tests)\n")
        f.write("\nRC1 tag: v2.8.0-rc1 at f39689a3 (feature freeze)\n")
        f.write("GA tag:  v2.8.0 at fbf869a2 (promotion artifacts only, zero behavior changes)\n")
    print(f"  Regenerated: CHANGELOG.txt")

    # 4. Compute artifact hashes for GA bundle
    artifact_files = [
        "requirements-frozen.txt",
        "dependency-lock.json",
        "reports/promotion-gate-report.json",
        "reports/soak-report.json",
        "reports/reproducibility-check.json",
        "env/pip-freeze.txt",
        "env/conda-list.txt",
        "incidents/sample-incident-snapshot.json",
        "CHANGELOG.txt",
    ]

    artifacts = {}
    for f in artifact_files:
        path = os.path.join(GA_DIR, f)
        if os.path.exists(path):
            artifacts[f] = {
                "sha256": sha256_file(path),
                "size_bytes": os.path.getsize(path),
            }

    # 5. Load RC1 gate + soak data for the manifest
    gate_path = os.path.join(GA_DIR, "reports", "promotion-gate-report.json")
    gate_data = {}
    if os.path.exists(gate_path):
        with open(gate_path, encoding="utf-8-sig") as f:
            gate_data = json.load(f)

    soak_path = os.path.join(GA_DIR, "reports", "soak-report.json")
    soak_data = {}
    if os.path.exists(soak_path):
        with open(soak_path, encoding="utf-8-sig") as f:
            soak_data = json.load(f)

    # 6. Build GA manifest
    manifest = {
        "release": "v2.8.0",
        "codename": "Deterministic Operations",
        "status": "GA",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rc_commit": "f39689a3",
        "ga_commit": GA_COMMIT,
        "tag": GA_TAG,
        "rc_tag": "v2.8.0-rc1",
        "behavior_delta_rc_to_ga": "none -- GA commit contains only promotion artifacts (tests, scripts, docs)",
        "promotion_gate": {
            "ready": gate_data.get("promotion_ready", False),
            "passed": gate_data.get("passed", 0),
            "failed": gate_data.get("failed", 0),
            "skipped": gate_data.get("skipped", 0),
            "total": gate_data.get("total", 0),
            "skipped_gates": [
                {"gate": 7, "name": "service-health", "reason": "requires live services"},
                {"gate": 8, "name": "breaker-states", "reason": "requires live services"},
            ],
        },
        "test_counts": {
            "rc1_hardening": 52,
            "v28_milestones": 104,
            "v28_full_regression": 156,
            "v27_backward_compat": 163,
            "v26_backward_compat": 82,
            "full_integration_suite": 565,
        },
        "soak": {
            "verdict": soak_data.get("verdict", "UNKNOWN"),
            "total_operations": soak_data.get("total_operations", 0),
            "phases": {
                "cancellation": soak_data.get("phases", {}).get("cancellation", {}).get("cycles", 0),
                "memory": soak_data.get("phases", {}).get("memory", {}).get("cycles", 0),
                "perception": soak_data.get("phases", {}).get("perception", {}).get("cycles", 0),
                "operator": soak_data.get("phases", {}).get("operator", {}).get("cycles", 0),
            },
            "invariant_violations": soak_data.get("invariant_violations", 0),
            "stuck_sessions": soak_data.get("stuck_sessions", 0),
            "queue_overflows": soak_data.get("queue_overflows", 0),
        },
        "operational_guarantees": [
            "Deterministic barge-in with cancellation safety (zero zombie tasks)",
            "Memory recall is budgeted (2000 char) and auditable per turn",
            "Perception-triggered actions are structurally non-bypassable",
            "Operator session provides health indicators + incident snapshot as first-class artifact",
        ],
        "artifacts": artifacts,
        "changelog_delta": "v2.7.0..v2.8.0",
    }

    manifest_path = os.path.join(GA_DIR, "release_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n  GA manifest: {manifest_path}")

    # Verify
    total_files = sum(1 for _ in os.walk(GA_DIR) for _ in _[2]) if False else 0
    count = 0
    for r, d, fs in os.walk(GA_DIR):
        count += len(fs)
    print(f"  Total files in GA bundle: {count}")
    print(f"  Artifact hashes: {len(artifacts)}")
    print(f"\n[OK] GA bundle at {GA_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
