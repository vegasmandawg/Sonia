#!/usr/bin/env python3
"""
v4.2 Epic 2: Chaos Recovery Determinism at Scale Gate
======================================================
10 real checks replacing the M0 placeholder.
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

GATE_ID = "v42-epic2-chaos-recovery-gate"
MODULE_DIR = os.path.join("S:", "services", "api-gateway")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    t0 = time.time()
    results = []
    passed = 0

    def check(name, fn):
        nonlocal passed
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"ERROR: {e}"
        results.append({"check": name, "verdict": "PASS" if ok else "FAIL", "detail": detail})
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}: {detail}")
        if ok:
            passed += 1

    # Load modules
    chaos = load_module("chaos_profile_policy", os.path.join(MODULE_DIR, "chaos_profile_policy.py"))
    restore = load_module("restore_invariant_policy", os.path.join(MODULE_DIR, "restore_invariant_policy.py"))
    replay = load_module("replay_determinism_policy", os.path.join(MODULE_DIR, "replay_determinism_policy.py"))
    retry = load_module("retry_breaker_policy", os.path.join(MODULE_DIR, "retry_breaker_policy.py"))
    incident = load_module("incident_lineage_policy", os.path.join(MODULE_DIR, "incident_lineage_policy.py"))

    # 1. Chaos profile registry exists, versioned, and hash-stable
    def c1():
        reg = chaos.ChaosProfileRegistry()
        s = chaos.ChaosScenario("s1", chaos.ScenarioType.ADAPTER_TIMEOUT, 5000, 2, 1, "test")
        p = chaos.ChaosProfile("p1", 1, (s,), "test profile")
        reg.register(p)
        exists = reg.get("p1") is not None
        stable = reg.verify_hash_stability("p1")
        fp1 = p.fingerprint
        fp2 = p.fingerprint
        return exists and stable["valid"] and fp1 == fp2, f"exists={exists}, stable={stable['valid']}, deterministic={fp1==fp2}"
    check("chaos_profile_registry_versioned_hash_stable", c1)

    # 2. Scenario bounds enforced
    def c2():
        reg = chaos.ChaosProfileRegistry()
        valid_s = chaos.ChaosScenario("s1", chaos.ScenarioType.ADAPTER_TIMEOUT, 5000, 2, 1, "ok")
        bounded = reg.check_bounds(valid_s)
        timeout_rejected = False
        try:
            chaos.ChaosScenario("s2", chaos.ScenarioType.ADAPTER_TIMEOUT, chaos.MAX_TIMEOUT_MS + 1, 0, 1, "bad")
        except ValueError:
            timeout_rejected = True
        retries_rejected = False
        try:
            chaos.ChaosScenario("s3", chaos.ScenarioType.ADAPTER_TIMEOUT, 1000, chaos.MAX_RETRIES + 1, 1, "bad")
        except ValueError:
            retries_rejected = True
        return bounded["bounded"] and timeout_rejected and retries_rejected, \
            f"bounded={bounded['bounded']}, timeout_rej={timeout_rejected}, retries_rej={retries_rejected}"
    check("scenario_bounds_enforced", c2)

    # 3. Restore preconditions deterministic
    def c3():
        pol1 = restore.RestoreInvariantPolicy()
        pol2 = restore.RestoreInvariantPolicy()
        m = restore.BackupManifest("b1", "hash_abc", 10, "ns1", "2026-01-01T00:00:00Z")
        r1 = pol1.check_preconditions(m, "hash_abc", "ns1", False)
        r2 = pol2.check_preconditions(m, "hash_abc", "ns1", False)
        same = r1["all_met"] == r2["all_met"] and r1["all_met"] is True
        # Bad hash should deterministically fail
        r3 = pol1.check_preconditions(m, "WRONG", "ns1", False)
        r4 = pol2.check_preconditions(m, "WRONG", "ns1", False)
        bad_same = r3["all_met"] == r4["all_met"] and r3["all_met"] is False
        return same and bad_same, f"good_deterministic={same}, bad_deterministic={bad_same}"
    check("restore_preconditions_deterministic", c3)

    # 4. Restore postconditions verify state integrity and parity
    def c4():
        pol = restore.RestoreInvariantPolicy()
        m = restore.BackupManifest("b1", "hash_abc", 10, "ns1", "2026-01-01T00:00:00Z")
        good = pol.check_postconditions(m, 10, "hash_abc")
        bad_count = pol.check_postconditions(m, 5, "hash_abc")
        bad_hash = pol.check_postconditions(m, 10, "WRONG")
        ok = good["all_passed"] and not bad_count["all_passed"] and not bad_hash["all_passed"]
        return ok, f"good={good['all_passed']}, bad_count={bad_count['all_passed']}, bad_hash={bad_hash['all_passed']}"
    check("restore_postconditions_integrity_parity", c4)

    # 5. Backup hash verification enforced before restore
    def c5():
        pol = restore.RestoreInvariantPolicy()
        m = restore.BackupManifest("b1", "hash_abc", 10, "ns1", "2026-01-01T00:00:00Z")
        ok_verify = pol.verify_backup_hash(m, "hash_abc")
        bad_verify = pol.verify_backup_hash(m, "CORRUPTED")
        ok = ok_verify["verified"] and not bad_verify["verified"]
        return ok, f"valid_hash={ok_verify['verified']}, corrupted={bad_verify['verified']}"
    check("backup_hash_verification_enforced", c5)

    # 6. DLQ dry-run contract differs from live replay
    def c6():
        pol = replay.ReplayDeterminismPolicy()
        entry = replay.DLQEntry("e1", "create_memory", "hash_a", "timeout", 1, "ns1")
        dry = pol.evaluate_replay(entry, replay.ReplayMode.DRY_RUN)
        live = pol.evaluate_replay(entry, replay.ReplayMode.LIVE)
        dry_ok = not dry.side_effects and dry.outcome == replay.ReplayOutcome.SUCCESS
        live_ok = live.side_effects and live.outcome == replay.ReplayOutcome.SUCCESS
        dry_contract = pol.check_dry_run_contract(dry)
        live_contract = pol.check_live_contract(live)
        ok = dry_ok and live_ok and dry_contract["valid"] and live_contract["valid"]
        return ok, f"dry_no_fx={dry_ok}, live_fx={live_ok}, contracts={dry_contract['valid'] and live_contract['valid']}"
    check("dlq_dry_run_vs_live_contract", c6)

    # 7. Replay idempotency invariants
    def c7():
        pol = replay.ReplayDeterminismPolicy()
        entry = replay.DLQEntry("e1", "action", "hash_a", "timeout", 1, "ns1")
        r1 = pol.evaluate_replay(entry, replay.ReplayMode.LIVE)
        r2 = pol.evaluate_replay(entry, replay.ReplayMode.LIVE)
        first_ok = r1.outcome == replay.ReplayOutcome.SUCCESS
        dup_ok = r2.outcome == replay.ReplayOutcome.SKIPPED_DUPLICATE and not r2.side_effects
        return first_ok and dup_ok, f"first={r1.outcome.value}, second={r2.outcome.value}"
    check("replay_idempotency_invariants", c7)

    # 8. Retry taxonomy completeness
    def c8():
        pol = retry.RetryTaxonomyPolicy()
        result = pol.check_completeness()
        complete = result["complete"]
        # Verify deterministic decisions
        d1 = pol.decide("timeout", 0)
        d2 = pol.decide("timeout", 0)
        deterministic = d1 == d2
        return complete and deterministic, f"complete={complete}, covered={result['covered']}, deterministic={deterministic}"
    check("retry_taxonomy_completeness", c8)

    # 9. Breaker FSM transition determinism
    def c9():
        b1 = retry.BreakerFSM("test1", failure_threshold=2)
        b2 = retry.BreakerFSM("test2", failure_threshold=2)
        for b in [b1, b2]:
            b.record_failure()
            b.record_failure()
            b.attempt_reset()
            b.record_success()
        same_state = b1.state == b2.state
        # Illegal transition check
        illegal = not b1.check_transition_validity("closed", "half_open")
        legal = b1.check_transition_validity("closed", "open")
        ok = same_state and illegal and legal
        return ok, f"deterministic={same_state}, illegal_blocked={illegal}, legal_ok={legal}"
    check("breaker_fsm_transition_determinism", c9)

    # 10. Incident lineage completeness
    def c10():
        pol = incident.IncidentLineagePolicy()
        r1 = incident.IncidentRecord(
            "i1", "c1", "2026-01-01T00:00:00Z", incident.Severity.HIGH,
            "timeout", "api-gateway", "Root incident", incident.ResolutionStatus.OPEN,
        )
        r2 = incident.IncidentRecord(
            "i2", "c2", "2026-01-01T01:00:00Z", incident.Severity.MEDIUM,
            "execution_error", "memory-engine", "Child incident", incident.ResolutionStatus.INVESTIGATING,
            parent_correlation_id="c1",
        )
        pol.register(r1)
        pol.register(r2)
        comp1 = pol.check_completeness("i1")
        comp2 = pol.check_completeness("i2")
        continuity = pol.check_correlation_continuity("c1")
        chain = pol.check_chain_completeness("c1")
        ok = (comp1["complete"] and comp2["complete"]
              and continuity["continuous"] and chain["all_complete"])
        return ok, f"i1_complete={comp1['complete']}, i2_complete={comp2['complete']}, continuous={continuity['continuous']}, chain={chain['all_complete']}"
    check("incident_lineage_completeness", c10)

    total = 10
    elapsed = round(time.time() - t0, 3)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = {
        "epic": "E2",
        "gate": GATE_ID,
        "title": "Chaos Recovery Determinism at Scale",
        "checks": total,
        "passed": passed,
        "verdict": "PASS" if passed == total else "FAIL",
        "elapsed_s": elapsed,
        "retries": 0,
        "failure_class": None,
        "results": results,
        "timestamp": ts,
    }

    out_dir = os.path.join("S:", "reports", "audit")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"v42-epic2-chaos-recovery-{ts}.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n{passed}/{total} checks PASS")
    print(f"Artifact: {out_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
