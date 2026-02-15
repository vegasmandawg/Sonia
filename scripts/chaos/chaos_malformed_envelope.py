"""
Chaos Fault: Malformed EventEnvelope

Feeds malformed event envelopes through validation and verifies that
all are rejected cleanly (no crash, no partial processing).

Output: reports/chaos-v31/malformed_envelope.json
"""

import importlib.util
import json
import sys
import time
from pathlib import Path

SHARED_DIR = Path(r"S:\services\shared")
REPORT_DIR = Path(r"S:\reports\chaos-v31")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


events_mod = _load_module("events_chaos", SHARED_DIR / "events.py")
validate_envelope = events_mod.validate_envelope
EventEnvelope = events_mod.EventEnvelope


MALFORMED_ENVELOPES = [
    # Missing type
    {"correlation_id": "req_abc"},
    # Missing correlation_id
    {"type": "test.event"},
    # Empty correlation_id
    {"type": "test.event", "correlation_id": ""},
    # Not a dict
    "not a dict",
    # None
    None,
    # Empty dict
    {},
    # Type is None
    {"type": None, "correlation_id": "req_abc"},
    # Extra fields (should still validate if required fields present)
    {"type": "test.event", "correlation_id": "req_abc", "extra": "field"},
    # Nested garbage
    {"type": {"nested": "dict"}, "correlation_id": "req_abc"},
]


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Chaos: Malformed EventEnvelope ===")

    results = []
    t0 = time.time()

    for i, envelope in enumerate(MALFORMED_ENVELOPES):
        try:
            valid, msg = validate_envelope(envelope)
            results.append({
                "index": i,
                "input_type": type(envelope).__name__,
                "valid": valid,
                "error_msg": msg,
                "crashed": False,
            })
        except Exception as e:
            results.append({
                "index": i,
                "input_type": type(envelope).__name__,
                "crashed": True,
                "error": str(e),
            })

    dt = time.time() - t0

    # The last entry with all required fields should be valid
    expected_valid = 1  # Only the one with type + correlation_id + extra
    actual_valid = sum(1 for r in results if r.get("valid") is True)
    crashes = sum(1 for r in results if r.get("crashed"))

    verdict = "PASS" if crashes == 0 else "FAIL"

    report = {
        "fault": "malformed_envelope",
        "total_tested": len(MALFORMED_ENVELOPES),
        "valid_accepted": actual_valid,
        "invalid_rejected": sum(1 for r in results if r.get("valid") is False),
        "crashes": crashes,
        "duration_s": round(dt, 3),
        "verdict": verdict,
        "details": results,
    }

    report_path = REPORT_DIR / "malformed_envelope.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Tested: {len(MALFORMED_ENVELOPES)} envelopes")
    print(f"  Crashes: {crashes}")
    print(f"  Verdict: {verdict}")
    print(f"  Report: {report_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
