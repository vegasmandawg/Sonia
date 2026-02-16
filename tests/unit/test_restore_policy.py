"""Tests for restore_policy — pre/post conditions, hash verification."""
import sys, hashlib
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from restore_policy import (
    BackupRecord, RestoreCheck, RestoreVerdict,
    RestorePreconditionValidator, RestorePostconditionValidator,
    verify_backup_before_restore, RestorePreconditionError,
)


class TestPreconditions:
    def test_all_satisfied_passes(self):
        pre = RestorePreconditionValidator()
        for c in RestorePreconditionValidator.REQUIRED_PRECONDITIONS:
            pre.set_condition(c, True)
        assert pre.all_pass()
        assert len(pre.missing_preconditions()) == 0

    def test_missing_precondition_fails(self):
        pre = RestorePreconditionValidator()
        pre.set_condition("backup_exists", True)
        assert not pre.all_pass()
        missing = pre.missing_preconditions()
        assert len(missing) == 3
        assert "backup_hash_valid" in missing

    def test_unsatisfied_precondition_fails(self):
        pre = RestorePreconditionValidator()
        for c in RestorePreconditionValidator.REQUIRED_PRECONDITIONS:
            pre.set_condition(c, True)
        pre.set_condition("no_active_transactions", False)
        assert not pre.all_pass()

    def test_validate_returns_check_objects(self):
        pre = RestorePreconditionValidator()
        pre.set_condition("backup_exists", True)
        results = pre.validate()
        assert all(isinstance(r, RestoreCheck) for r in results)
        assert any(r.verdict == RestoreVerdict.FAIL for r in results)


class TestPostconditions:
    def test_all_satisfied_passes(self):
        post = RestorePostconditionValidator()
        for c in RestorePostconditionValidator.REQUIRED_POSTCONDITIONS:
            post.set_condition(c, True)
        assert post.all_pass()

    def test_invalid_postcondition_fails(self):
        post = RestorePostconditionValidator()
        post.set_condition("service_healthy", True)
        post.set_condition("no_data_corruption", False)
        assert not post.all_pass()
        assert "no_data_corruption" in post.failed_postconditions()


class TestBackupHash:
    def test_valid_hash_passes(self):
        content = "backup-data-v1"
        h = hashlib.sha256(content.encode()).hexdigest()
        br = BackupRecord("bk-1", "svc", "2025-01-01", h, content)
        assert br.verify_hash()
        result = verify_backup_before_restore(br)
        assert result.verdict == RestoreVerdict.PASS

    def test_corrupted_hash_fails(self):
        br = BackupRecord("bk-2", "svc", "2025-01-01", "badhash", "data")
        assert not br.verify_hash()
        result = verify_backup_before_restore(br)
        assert result.verdict == RestoreVerdict.FAIL

    def test_none_content_fails(self):
        br = BackupRecord("bk-3", "svc", "2025-01-01", "somehash")
        assert not br.verify_hash()
        result = verify_backup_before_restore(br)
        assert result.verdict == RestoreVerdict.FAIL
