"""
Tests for data durability policy module.
12+ tests covering migration monotonicity, backup chain integrity,
retention/restore consistency, and connection durability.
"""
import sys
import hashlib
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\memory-engine")

from durability_policy import (
    MigrationMonotonicityChecker,
    BackupChainVerifier,
    BackupEntry,
    RetentionConsistencyChecker,
    RetentionPolicy,
    ConnectionDurabilityChecker,
    ConnectionPolicy,
    DurabilityPolicyRunner,
    DurabilityVerdict,
    DurabilityReport,
    CheckResult,
)


class TestMigrationMonotonicity:
    def test_empty_migrations_skip(self):
        mc = MigrationMonotonicityChecker()
        r = mc.check_monotonicity()
        assert r.verdict == DurabilityVerdict.SKIP

    def test_monotonic_sequence_pass(self):
        mc = MigrationMonotonicityChecker()
        mc.register(1, "init")
        mc.register(2, "add_col")
        mc.register(3, "index")
        assert mc.check_monotonicity().verdict == DurabilityVerdict.PASS

    def test_duplicate_version_fail(self):
        mc = MigrationMonotonicityChecker()
        mc.register(1, "init")
        mc.register(2, "v2")
        mc.register(2, "v2_dup")
        assert mc.check_monotonicity().verdict == DurabilityVerdict.FAIL

    def test_continuity_pass(self):
        mc = MigrationMonotonicityChecker()
        mc.register(1, "a")
        mc.register(2, "b")
        mc.register(3, "c")
        assert mc.check_continuity().verdict == DurabilityVerdict.PASS

    def test_continuity_gap_fail(self):
        mc = MigrationMonotonicityChecker()
        mc.register(1, "a")
        mc.register(3, "c")
        r = mc.check_continuity()
        assert r.verdict == DurabilityVerdict.FAIL
        assert "2" in r.detail


class TestBackupChain:
    def test_valid_chain_pass(self):
        bv = BackupChainVerifier()
        bv.add_entry(BackupEntry("root", None, "aaa", 100))
        bv.add_entry(BackupEntry("b2", "root", "bbb", 200))
        assert bv.verify_chain().verdict == DurabilityVerdict.PASS

    def test_orphan_detected(self):
        bv = BackupChainVerifier()
        bv.add_entry(BackupEntry("root", None, "aaa", 100))
        bv.add_entry(BackupEntry("orphan", "missing_parent", "bbb", 200))
        assert bv.verify_chain().verdict == DurabilityVerdict.FAIL

    def test_no_root_fail(self):
        bv = BackupChainVerifier()
        bv.add_entry(BackupEntry("b1", "b0", "aaa", 100))
        bv.add_entry(BackupEntry("b2", "b1", "bbb", 200))
        r = bv.verify_chain()
        # b0 doesn't exist so b1 is orphan
        assert r.verdict == DurabilityVerdict.FAIL

    def test_hash_verification_pass(self):
        data = b"hello world"
        h = hashlib.sha256(data).hexdigest()
        bv = BackupChainVerifier()
        bv.add_entry(BackupEntry("b1", None, h, len(data)))
        r = bv.verify_hashes({"b1": data})
        assert r.verdict == DurabilityVerdict.PASS

    def test_hash_mismatch_fail(self):
        bv = BackupChainVerifier()
        bv.add_entry(BackupEntry("b1", None, "wrong_hash", 100))
        r = bv.verify_hashes({"b1": b"actual data"})
        assert r.verdict == DurabilityVerdict.FAIL


class TestRetention:
    def test_minimum_backups_pass(self):
        rc = RetentionConsistencyChecker(RetentionPolicy(min_backups=3))
        assert rc.check_minimum_backups(5).verdict == DurabilityVerdict.PASS

    def test_minimum_backups_fail(self):
        rc = RetentionConsistencyChecker(RetentionPolicy(min_backups=3))
        assert rc.check_minimum_backups(1).verdict == DurabilityVerdict.FAIL

    def test_restore_required_pass(self):
        rc = RetentionConsistencyChecker(RetentionPolicy(require_restore_test=True))
        assert rc.check_restore_capability(True).verdict == DurabilityVerdict.PASS

    def test_restore_not_tested_fail(self):
        rc = RetentionConsistencyChecker(RetentionPolicy(require_restore_test=True))
        assert rc.check_restore_capability(False).verdict == DurabilityVerdict.FAIL


class TestConnectionDurability:
    def test_wal_mode_pass(self):
        cc = ConnectionDurabilityChecker()
        assert cc.check_wal_mode("wal").verdict == DurabilityVerdict.PASS

    def test_wal_mode_fail(self):
        cc = ConnectionDurabilityChecker()
        assert cc.check_wal_mode("delete").verdict == DurabilityVerdict.FAIL

    def test_synchronous_normal_pass(self):
        cc = ConnectionDurabilityChecker()
        assert cc.check_synchronous("NORMAL").verdict == DurabilityVerdict.PASS

    def test_synchronous_off_fail(self):
        cc = ConnectionDurabilityChecker()
        assert cc.check_synchronous("OFF").verdict == DurabilityVerdict.FAIL

    def test_foreign_keys_enabled(self):
        cc = ConnectionDurabilityChecker()
        assert cc.check_foreign_keys(True).verdict == DurabilityVerdict.PASS

    def test_foreign_keys_disabled_fail(self):
        cc = ConnectionDurabilityChecker()
        assert cc.check_foreign_keys(False).verdict == DurabilityVerdict.FAIL

    def test_timeout_sufficient_pass(self):
        cc = ConnectionDurabilityChecker(ConnectionPolicy(busy_timeout_ms=5000))
        assert cc.check_timeout(10000).verdict == DurabilityVerdict.PASS

    def test_timeout_insufficient_fail(self):
        cc = ConnectionDurabilityChecker(ConnectionPolicy(busy_timeout_ms=5000))
        assert cc.check_timeout(1000).verdict == DurabilityVerdict.FAIL


class TestCompositeRunner:
    def test_runner_produces_report(self):
        runner = DurabilityPolicyRunner()
        runner.migration_checker.register(1, "init")
        runner.migration_checker.register(2, "v2")
        report = runner.run_all()
        assert isinstance(report, DurabilityReport)
        assert report.verdict in ("PASS", "FAIL")

    def test_report_to_dict(self):
        runner = DurabilityPolicyRunner()
        report = runner.run_all()
        d = report.to_dict()
        assert "checks" in d
        assert "verdict" in d
        assert isinstance(d["checks"], list)

    def test_emit_artifact(self):
        runner = DurabilityPolicyRunner()
        runner.migration_checker.register(1, "init")
        with tempfile.TemporaryDirectory() as td:
            path = runner.emit_artifact(td)
            assert Path(path).exists()
            import json
            data = json.loads(Path(path).read_text())
            assert data["verdict"] in ("PASS", "FAIL")
