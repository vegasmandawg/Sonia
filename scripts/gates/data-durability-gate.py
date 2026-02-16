"""
Data Durability Gate (10 checks)
================================
Verifies durability invariants: migration monotonicity, backup chain integrity,
retention/restore consistency, and connection durability assertions.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(r"S:\\")
sys.path.insert(0, str(ROOT / "services" / "memory-engine"))

checks = []


def check(name, fn):
    try:
        ok = fn()
        checks.append({"name": name, "result": "PASS" if ok else "FAIL"})
    except Exception as e:
        checks.append({"name": name, "result": "FAIL", "error": str(e)})


# 1. Durability policy module importable
def c1():
    import durability_policy
    return hasattr(durability_policy, "DurabilityPolicyRunner")
check("durability_module_importable", c1)


# 2. Migration monotonicity check works
def c2():
    from durability_policy import MigrationMonotonicityChecker, DurabilityVerdict
    mc = MigrationMonotonicityChecker()
    mc.register(1, "init")
    mc.register(2, "add_col")
    mc.register(3, "index")
    r = mc.check_monotonicity()
    return r.verdict == DurabilityVerdict.PASS
check("migration_monotonicity_pass", c2)


# 3. Non-monotonic migration detected (duplicate versions)
def c3():
    from durability_policy import MigrationMonotonicityChecker, DurabilityVerdict
    mc = MigrationMonotonicityChecker()
    mc.register(1, "init")
    mc.register(2, "v2")
    mc.register(2, "v2_dup")
    r = mc.check_monotonicity()
    return r.verdict == DurabilityVerdict.FAIL
check("non_monotonic_detected", c3)


# 4. Version continuity gap detection
def c4():
    from durability_policy import MigrationMonotonicityChecker, DurabilityVerdict
    mc = MigrationMonotonicityChecker()
    mc.register(1, "init")
    mc.register(3, "skip")
    r = mc.check_continuity()
    return r.verdict == DurabilityVerdict.FAIL
check("version_gap_detected", c4)


# 5. Backup chain integrity verification
def c5():
    from durability_policy import BackupChainVerifier, BackupEntry, DurabilityVerdict
    bv = BackupChainVerifier()
    bv.add_entry(BackupEntry("b1", None, "abc123", 100))
    bv.add_entry(BackupEntry("b2", "b1", "def456", 200))
    r = bv.verify_chain()
    return r.verdict == DurabilityVerdict.PASS
check("backup_chain_valid", c5)


# 6. Orphan backup detection
def c6():
    from durability_policy import BackupChainVerifier, BackupEntry, DurabilityVerdict
    bv = BackupChainVerifier()
    bv.add_entry(BackupEntry("b1", None, "abc", 100))
    bv.add_entry(BackupEntry("b2", "missing", "def", 200))
    r = bv.verify_chain()
    return r.verdict == DurabilityVerdict.FAIL
check("orphan_backup_detected", c6)


# 7. Retention minimum check
def c7():
    from durability_policy import RetentionConsistencyChecker, RetentionPolicy, DurabilityVerdict
    rc = RetentionConsistencyChecker(RetentionPolicy(min_backups=3))
    r_pass = rc.check_minimum_backups(5)
    r_fail = rc.check_minimum_backups(1)
    return r_pass.verdict == DurabilityVerdict.PASS and r_fail.verdict == DurabilityVerdict.FAIL
check("retention_minimum_enforced", c7)


# 8. Connection WAL mode check
def c8():
    from durability_policy import ConnectionDurabilityChecker, DurabilityVerdict
    cc = ConnectionDurabilityChecker()
    r_pass = cc.check_wal_mode("wal")
    r_fail = cc.check_wal_mode("delete")
    return r_pass.verdict == DurabilityVerdict.PASS and r_fail.verdict == DurabilityVerdict.FAIL
check("wal_mode_enforced", c8)


# 9. Connection synchronous mode check
def c9():
    from durability_policy import ConnectionDurabilityChecker, DurabilityVerdict
    cc = ConnectionDurabilityChecker()
    r_pass = cc.check_synchronous("NORMAL")
    r_fail = cc.check_synchronous("OFF")
    return r_pass.verdict == DurabilityVerdict.PASS and r_fail.verdict == DurabilityVerdict.FAIL
check("synchronous_mode_enforced", c9)


# 10. Composite report emittable
def c10():
    from durability_policy import DurabilityPolicyRunner
    runner = DurabilityPolicyRunner()
    runner.migration_checker.register(1, "init")
    runner.migration_checker.register(2, "v2")
    report = runner.run_all()
    d = report.to_dict()
    return (
        "checks" in d
        and "verdict" in d
        and isinstance(d["checks"], list)
        and d["passed"] >= 0
    )
check("composite_report_emittable", c10)


# ---- Report ----
ts = time.strftime("%Y%m%d-%H%M%S")
passed = sum(1 for c in checks if c["result"] == "PASS")
total = len(checks)
verdict = "PASS" if passed == total else "FAIL"

report = {
    "gate": "data-durability",
    "timestamp": ts,
    "checks": checks,
    "passed": passed,
    "total": total,
    "verdict": verdict,
}
out_dir = ROOT / "reports" / "audit"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"data-durability-gate-{ts}.json"
out_path.write_text(json.dumps(report, indent=2))

print(f"\n=== Data Durability Gate ({passed}/{total}) ===\n")
for c in checks:
    print(f"  [{c['result']}] {c['name']}")
print(f"\nArtifact: {out_path}\n")
print(verdict)
sys.exit(0 if verdict == "PASS" else 1)
