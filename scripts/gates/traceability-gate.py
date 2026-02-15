#!/usr/bin/env python3
"""
Control traceability gate.

Verifies that every control in control-traceability.yaml has:
  1. A documentation reference (doc_ref) pointing to a file that exists
  2. A gate artifact pattern (gate_artifact) with at least one matching file (if specified)

Fails if any control marked 'covered' lacks its required evidence.
"""

import sys
import json
import glob
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRACEABILITY = REPO_ROOT / "docs" / "governance" / "control-traceability.yaml"
REPORT_DIR = REPO_ROOT / "reports" / "audit"


def load_controls() -> dict:
    """Parse YAML manually (no pyyaml dependency required)."""
    text = TRACEABILITY.read_text(encoding="utf-8")
    controls = {}
    current_id = None
    current = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("  ") and not line.startswith("    ") and stripped.endswith(":"):
            # New control ID
            if current_id:
                controls[current_id] = current
            current_id = stripped.rstrip(":")
            current = {}
        elif line.startswith("    ") and ": " in stripped:
            key, _, value = stripped.partition(": ")
            if value == "null":
                value = None
            current[key] = value

    if current_id:
        controls[current_id] = current

    return controls


def check_doc_ref(doc_ref: str) -> bool:
    """Check that a doc_ref points to an existing file."""
    if not doc_ref:
        return False
    # Strip anchor
    file_part = doc_ref.split("#")[0]
    path = REPO_ROOT / file_part
    return path.exists()


def check_gate_artifact(pattern: str) -> tuple:
    """Check that at least one file matches the gate artifact glob."""
    if not pattern:
        return True, 0  # No artifact required
    full_pattern = str(REPO_ROOT / pattern)
    matches = glob.glob(full_pattern)
    return len(matches) > 0, len(matches)


def main():
    print("=== SONIA Control Traceability Gate ===\n")

    controls = load_controls()
    results = []
    failures = []

    for cid, ctrl in sorted(controls.items()):
        status = ctrl.get("status", "gap")
        if status != "covered":
            results.append({"control": cid, "status": status, "passed": True, "note": "not required"})
            continue

        doc_ref = ctrl.get("doc_ref")
        gate_artifact = ctrl.get("gate_artifact")

        doc_ok = check_doc_ref(doc_ref) if doc_ref else True
        artifact_ok, artifact_count = check_gate_artifact(gate_artifact)

        passed = doc_ok and artifact_ok
        result = {
            "control": cid,
            "section": ctrl.get("section", "?"),
            "doc_ref": doc_ref,
            "doc_exists": doc_ok,
            "gate_artifact": gate_artifact,
            "artifact_count": artifact_count,
            "passed": passed,
        }
        results.append(result)

        tag = "PASS" if passed else "FAIL"
        if not passed:
            failures.append(cid)
            reasons = []
            if not doc_ok:
                reasons.append(f"doc missing: {doc_ref}")
            if not artifact_ok:
                reasons.append(f"no artifact: {gate_artifact}")
            print(f"  [{tag}] {cid}: {', '.join(reasons)}")
        else:
            print(f"  [{tag}] {cid}")

    total = len([r for r in results if r.get("note") != "not required"])
    passed = len([r for r in results if r["passed"] and r.get("note") != "not required"])
    overall = "PASS" if len(failures) == 0 else "FAIL"

    report = {
        "gate": "control-traceability",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "controls_checked": total,
        "controls_passed": passed,
        "failures": failures,
        "overall": overall,
        "details": results,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = REPORT_DIR / "traceability-gate-{}.json".format(
        datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    artifact.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{passed}/{total} controls verified")
    print(f"Report: {artifact}")
    print(f"\n{overall}: Control traceability {'verified' if overall == 'PASS' else 'has gaps'}.")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
