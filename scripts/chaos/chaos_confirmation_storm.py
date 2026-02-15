"""
Chaos Fault: Confirmation Storm

Floods PerceptionActionGate with rapid require/approve/deny/expire
cycles to verify no state corruption or bypass under pressure.

Output: reports/chaos-v31/confirmation_storm.json
"""

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


gate_mod = _load_module("pag_chaos", GATEWAY_DIR / "perception_action_gate.py")
PerceptionActionGate = gate_mod.PerceptionActionGate
ConfirmationBypassError = gate_mod.ConfirmationBypassError


STORM_ROUNDS = 5
OPS_PER_ROUND = 40  # Must be <= MAX_PENDING (50)


def run_storm():
    results = []

    for round_idx in range(STORM_ROUNDS):
        gate = PerceptionActionGate(ttl_seconds=0.2)  # 200ms TTL
        reqs = []

        # Phase 1: Rapid creation
        for i in range(OPS_PER_ROUND):
            try:
                req = gate.require_confirmation(
                    action="file.read",
                    scene_id=f"storm_r{round_idx}_s{i}",
                    correlation_id=f"req_storm_{round_idx}_{i}",
                )
                reqs.append(req)
            except ConfirmationBypassError:
                break

        # Phase 2: Approve first third, deny second third, let rest expire
        third = len(reqs) // 3
        approved = 0
        denied = 0
        executed = 0

        for i in range(third):
            if gate.approve(reqs[i].requirement_id):
                approved += 1
                try:
                    gate.validate_execution(reqs[i].requirement_id)
                    executed += 1
                except ConfirmationBypassError:
                    pass

        for i in range(third, 2 * third):
            if gate.deny(reqs[i].requirement_id, reason="storm"):
                denied += 1

        # Phase 3: Wait for TTL then expire stale
        time.sleep(0.3)
        gate._expire_stale()

        stats = gate.get_stats()
        bypass = stats["bypass_attempts"]

        results.append({
            "round": round_idx,
            "created": len(reqs),
            "approved": approved,
            "denied": denied,
            "executed": executed,
            "expired": stats["total_expired"],
            "bypass_attempts": bypass,
            "pending_after": stats["pending_count"],
        })

    return results


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Chaos: Confirmation Storm ===")

    t0 = time.time()
    try:
        rounds = run_storm()
        crashed = False
    except Exception as e:
        rounds = []
        crashed = True
        print(f"  CRASH: {e}")

    dt = time.time() - t0

    total_bypass = sum(r.get("bypass_attempts", 0) for r in rounds)
    total_pending = sum(r.get("pending_after", 0) for r in rounds)

    verdict = "PASS" if not crashed and total_bypass == 0 and total_pending == 0 else "FAIL"

    report = {
        "fault": "confirmation_storm",
        "rounds": STORM_ROUNDS,
        "ops_per_round": OPS_PER_ROUND,
        "duration_s": round(dt, 3),
        "total_bypass_attempts": total_bypass,
        "total_pending_remaining": total_pending,
        "crashed": crashed,
        "verdict": verdict,
        "round_details": rounds,
    }

    report_path = REPORT_DIR / "confirmation_storm.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Rounds: {STORM_ROUNDS} x {OPS_PER_ROUND} ops")
    print(f"  Bypass attempts: {total_bypass}")
    print(f"  Verdict: {verdict}")
    print(f"  Report: {report_path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
