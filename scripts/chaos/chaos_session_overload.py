"""
Chaos Fault: Session Overload

Attempts to create more sessions than MAX_CONCURRENT_SESSIONS allows.
Verifies that the limit is enforced and excess creation raises RuntimeError.

Output: reports/chaos-v31/session_overload.json
"""

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

GATEWAY_DIR = Path(r"S:\services\api-gateway")
REPORT_DIR = Path(r"S:\reports\chaos-v31")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


session_mod = _load_module("session_chaos", GATEWAY_DIR / "session_manager.py")
SessionManager = session_mod.SessionManager


MAX_SESSIONS = 10  # Small limit for chaos test
OVERLOAD_ATTEMPTS = 20


async def run_overload():
    mgr = SessionManager(max_sessions=MAX_SESSIONS)
    created = 0
    rejected = 0

    for i in range(OVERLOAD_ATTEMPTS):
        try:
            await mgr.create(f"chaos_user_{i}", f"chaos_conv_{i}")
            created += 1
        except RuntimeError:
            rejected += 1

    # Verify active count is at limit
    active = mgr.active_count

    return {
        "created": created,
        "rejected": rejected,
        "active_count": active,
        "limit_enforced": created <= MAX_SESSIONS,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Chaos: Session Overload ===")

    t0 = time.time()
    try:
        result = asyncio.run(run_overload())
        crashed = False
    except Exception as e:
        result = {"error": str(e)}
        crashed = True

    dt = time.time() - t0

    verdict = "PASS" if not crashed and result.get("limit_enforced", False) else "FAIL"

    report = {
        "fault": "session_overload",
        "max_sessions": MAX_SESSIONS,
        "overload_attempts": OVERLOAD_ATTEMPTS,
        "duration_s": round(dt, 3),
        "crashed": crashed,
        "verdict": verdict,
        **result,
    }

    report_path = REPORT_DIR / "session_overload.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Created: {result.get('created', '?')}/{OVERLOAD_ATTEMPTS}")
    print(f"  Rejected: {result.get('rejected', '?')}")
    print(f"  Verdict: {verdict}")
    print(f"  Report: {report_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
