"""Tests for evidence_integrity.py — 9 tests."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import hashlib
import pytest
from evidence_integrity import (
    EvidenceRecord, EvidenceIntegrityChecker,
    EvidenceHashMissingError, TimestampInconsistencyError,
)


def _make_record(aid="art-001", sha="a" * 64, ts="2026-02-16T10:00:00+00:00",
                 source="pytest", atype="gate_report"):
    return EvidenceRecord(aid, f"reports/{aid}.json", sha, ts, source, atype)


class TestHashPresence:
    def test_valid_hash_present(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001"))
        result = c.check_hash_presence(["art-001"])
        assert result["art-001"] is True

    def test_missing_artifact_fails(self):
        c = EvidenceIntegrityChecker()
        result = c.check_hash_presence(["art-missing"])
        assert result["art-missing"] is False

    def test_short_hash_fails(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", sha="abc"))
        result = c.check_hash_presence(["art-001"])
        assert result["art-001"] is False


class TestHashValidity:
    def test_content_matches_hash(self):
        content = b"hello world"
        sha = hashlib.sha256(content).hexdigest()
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", sha=sha))
        assert c.check_hash_validity("art-001", content) is True

    def test_content_mismatch(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", sha="b" * 64))
        assert c.check_hash_validity("art-001", b"hello") is False


class TestTimestampMonotonicity:
    def test_monotonic_sequence_passes(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", ts="2026-02-16T10:00:00+00:00"))
        c.register(_make_record("art-002", ts="2026-02-16T11:00:00+00:00"))
        c.define_sequence("seq1", ["art-001", "art-002"])
        violations = c.check_timestamp_monotonicity()
        assert len(violations) == 0

    def test_non_monotonic_detected(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", ts="2026-02-16T12:00:00+00:00"))
        c.register(_make_record("art-002", ts="2026-02-16T10:00:00+00:00"))
        c.define_sequence("seq1", ["art-001", "art-002"])
        violations = c.check_timestamp_monotonicity()
        assert len(violations) == 1


class TestSourceAndTypeValidity:
    def test_valid_source(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", source="pytest"))
        result = c.check_source_validity()
        assert result["art-001"] is True

    def test_invalid_source(self):
        c = EvidenceIntegrityChecker()
        c.register(_make_record("art-001", source="unknown_tool"))
        result = c.check_source_validity()
        assert result["art-001"] is False
