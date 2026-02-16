"""Tests for cleanroom_parity — artifact fingerprinting and comparison."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from cleanroom_parity import (
    ArtifactFingerprint, CleanroomParityChecker,
    compute_artifact_hash, fingerprint_from_content,
)


class TestFingerprint:
    def test_matching_artifacts(self):
        fp1 = fingerprint_from_content("file.json", "content")
        fp2 = fingerprint_from_content("file.json", "content")
        assert fp1.matches(fp2)

    def test_different_content_no_match(self):
        fp1 = fingerprint_from_content("file.json", "content-a")
        fp2 = fingerprint_from_content("file.json", "content-b")
        assert not fp1.matches(fp2)

    def test_hash_deterministic(self):
        h1 = compute_artifact_hash("test-data")
        h2 = compute_artifact_hash("test-data")
        assert h1 == h2 and len(h1) == 64


class TestParity:
    def test_full_parity(self):
        checker = CleanroomParityChecker()
        for f in ["a.json", "b.json"]:
            fp = fingerprint_from_content(f, "data")
            checker.register_original(fp)
            checker.register_cleanroom(fp)
        result = checker.check_parity()
        assert result.overall_parity
        assert result.matched == 2

    def test_mismatch_detected(self):
        checker = CleanroomParityChecker()
        checker.register_original(fingerprint_from_content("a.json", "v1"))
        checker.register_cleanroom(fingerprint_from_content("a.json", "v2"))
        result = checker.check_parity()
        assert not result.overall_parity
        assert "a.json" in result.mismatched

    def test_missing_in_cleanroom(self):
        checker = CleanroomParityChecker()
        checker.register_original(fingerprint_from_content("a.json", "data"))
        result = checker.check_parity()
        assert not result.overall_parity
        assert "a.json" in result.missing_in_cleanroom

    def test_extra_in_cleanroom(self):
        checker = CleanroomParityChecker()
        checker.register_cleanroom(fingerprint_from_content("extra.json", "data"))
        result = checker.check_parity()
        assert not result.overall_parity
        assert "extra.json" in result.extra_in_cleanroom

    def test_to_dict(self):
        checker = CleanroomParityChecker()
        result = checker.check_parity()
        d = result.to_dict()
        assert "overall_parity" in d
