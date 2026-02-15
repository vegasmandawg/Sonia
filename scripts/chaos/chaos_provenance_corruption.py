"""
Chaos Fault: Provenance Corruption Attempt

Attempts to create provenance records with invalid/empty required fields.
Verifies that ProvenanceTracker rejects all corrupt inputs.

Output: reports/chaos-v31/provenance_corruption.json
"""

import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

MEMORY_DIR = Path(r"S:\services\memory-engine")
REPORT_DIR = Path(r"S:\reports\chaos-v31")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


prov_mod = _load_module("prov_chaos", MEMORY_DIR / "core" / "provenance.py")
ProvenanceTracker = prov_mod.ProvenanceTracker


CORRUPTION_ATTEMPTS = [
    {"memory_id": "mem_1", "scene_id": "", "correlation_id": "req_1", "trigger": "test", "model_used": "m1"},
    {"memory_id": "mem_2", "scene_id": "s1", "correlation_id": "", "trigger": "test", "model_used": "m1"},
    {"memory_id": "mem_3", "scene_id": "s1", "correlation_id": "req_1", "trigger": "", "model_used": "m1"},
    {"memory_id": "mem_4", "scene_id": "s1", "correlation_id": "req_1", "trigger": "test", "model_used": ""},
    {"memory_id": "mem_5", "scene_id": "   ", "correlation_id": "req_1", "trigger": "test", "model_used": "m1"},
    {"memory_id": "mem_6", "scene_id": "s1", "correlation_id": "   ", "trigger": "test", "model_used": "m1"},
]


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Chaos: Provenance Corruption ===")

    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_db.connection = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=mock_conn),
        __exit__=MagicMock(return_value=False),
    ))

    tracker = ProvenanceTracker(mock_db)

    results = []
    t0 = time.time()

    for i, attempt in enumerate(CORRUPTION_ATTEMPTS):
        try:
            tracker.track_perception(**attempt)
            results.append({
                "index": i,
                "rejected": False,
                "error": None,
                "detail": "ACCEPTED (should have been rejected!)",
            })
        except ValueError as e:
            results.append({
                "index": i,
                "rejected": True,
                "error": str(e),
                "detail": "Correctly rejected",
            })
        except Exception as e:
            results.append({
                "index": i,
                "rejected": False,
                "error": str(e),
                "detail": f"Unexpected error type: {type(e).__name__}",
            })

    dt = time.time() - t0

    rejected_count = sum(1 for r in results if r["rejected"])
    accepted_count = sum(1 for r in results if not r["rejected"])

    verdict = "PASS" if accepted_count == 0 else "FAIL"

    report = {
        "fault": "provenance_corruption",
        "total_attempts": len(CORRUPTION_ATTEMPTS),
        "rejected": rejected_count,
        "accepted_incorrectly": accepted_count,
        "duration_s": round(dt, 3),
        "verdict": verdict,
        "details": results,
    }

    report_path = REPORT_DIR / "provenance_corruption.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Attempts: {len(CORRUPTION_ATTEMPTS)}")
    print(f"  Rejected: {rejected_count}")
    print(f"  Accepted (bad): {accepted_count}")
    print(f"  Verdict: {verdict}")
    print(f"  Report: {report_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
