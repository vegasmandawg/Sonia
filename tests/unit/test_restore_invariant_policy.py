"""Tests for restore_invariant_policy.py — v4.2 E2."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from restore_invariant_policy import (
    BackupManifest, RestoreInvariantPolicy, PreconditionStatus,
)


class TestBackupManifest:
    def test_valid_manifest(self):
        m = BackupManifest("b1", "abc123", 10, "ns1", "2026-01-01T00:00:00Z")
        assert m.backup_id == "b1"
        assert m.fingerprint

    def test_empty_backup_id_rejected(self):
        with pytest.raises(ValueError, match="backup_id"):
            BackupManifest("", "abc123", 10, "ns1", "2026-01-01T00:00:00Z")

    def test_empty_hash_rejected(self):
        with pytest.raises(ValueError, match="content_hash"):
            BackupManifest("b1", "", 10, "ns1", "2026-01-01T00:00:00Z")

    def test_negative_entry_count_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            BackupManifest("b1", "abc", -1, "ns1", "2026-01-01T00:00:00Z")


class TestRestoreInvariantPolicy:
    def _make_manifest(self):
        return BackupManifest("b1", "hash_abc", 10, "ns1", "2026-01-01T00:00:00Z")

    def test_all_preconditions_met(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_preconditions(m, "hash_abc", "ns1", active_writes=False)
        assert result["all_met"] is True
        assert result["restore_allowed"] is True

    def test_corrupted_backup_hash_fails(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_preconditions(m, "CORRUPTED_HASH", "ns1", active_writes=False)
        assert result["all_met"] is False
        hash_result = [r for r in result["results"] if r["name"] == "hash_verified"][0]
        assert hash_result["status"] == PreconditionStatus.UNMET.value

    def test_missing_namespace_match_fails(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_preconditions(m, "hash_abc", "wrong_ns", active_writes=False)
        assert result["all_met"] is False

    def test_active_writes_blocks_restore(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_preconditions(m, "hash_abc", "ns1", active_writes=True)
        assert result["all_met"] is False

    def test_backup_hash_verification_standalone(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        ok = pol.verify_backup_hash(m, "hash_abc")
        assert ok["verified"] is True
        bad = pol.verify_backup_hash(m, "WRONG")
        assert bad["verified"] is False

    def test_postconditions_pass(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_postconditions(m, 10, "hash_abc")
        assert result["all_passed"] is True
        assert result["integrity_verified"] is True

    def test_postcondition_count_mismatch(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_postconditions(m, 5, "hash_abc")
        assert result["all_passed"] is False

    def test_postcondition_hash_mismatch(self):
        pol = RestoreInvariantPolicy()
        m = self._make_manifest()
        result = pol.check_postconditions(m, 10, "WRONG_HASH")
        assert result["all_passed"] is False
