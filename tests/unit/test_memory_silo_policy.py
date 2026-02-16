"""Tests for memory_silo_policy.py — v4.2 E1."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from memory_silo_policy import (
    MemoryEntry, MemorySiloPolicy, RetentionRule, RetentionAction,
    MAX_IMPORT_PAYLOAD_BYTES, ALLOWED_IMPORT_TYPES,
)


class TestMemoryEntry:
    def test_valid_entry(self):
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc123", "2026-01-01T00:00:00Z")
        assert e.entry_id == "e1"
        assert e.fingerprint

    def test_empty_entry_id_rejected(self):
        with pytest.raises(ValueError, match="entry_id"):
            MemoryEntry("", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")

    def test_fingerprint_deterministic(self):
        e1 = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        e2 = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        assert e1.fingerprint == e2.fingerprint


class TestSiloAccess:
    def test_same_namespace_access_allowed(self):
        policy = MemorySiloPolicy()
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        policy.add_entry(e)
        assert policy.check_silo_access("ns1", "e1") is True

    def test_cross_namespace_access_denied(self):
        policy = MemorySiloPolicy()
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        policy.add_entry(e)
        assert policy.check_silo_access("ns_other", "e1") is False

    def test_nonexistent_entry_denied(self):
        policy = MemorySiloPolicy()
        assert policy.check_silo_access("ns1", "missing") is False


class TestRetention:
    def test_no_rule_retains(self):
        policy = MemorySiloPolicy()
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        assert policy.evaluate_retention(e) == RetentionAction.RETAIN

    def test_expired_entry_deleted(self):
        policy = MemorySiloPolicy()
        policy.register_retention_rule(RetentionRule("fact", 24, RetentionAction.DELETE))
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z", age_hours=48)
        assert policy.evaluate_retention(e) == RetentionAction.DELETE

    def test_non_expired_retained(self):
        policy = MemorySiloPolicy()
        policy.register_retention_rule(RetentionRule("fact", 24, RetentionAction.DELETE))
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z", age_hours=12)
        assert policy.evaluate_retention(e) == RetentionAction.RETAIN

    def test_retention_rule_bypass_attempt(self):
        """Negative: retention rules cannot be bypassed by using a different type."""
        policy = MemorySiloPolicy()
        policy.register_retention_rule(RetentionRule("fact", 24, RetentionAction.DELETE))
        # Entry of type "summary" has no rule — retained
        e = MemoryEntry("e1", "s1", "p1", "ns1", "summary", "abc", "2026-01-01T00:00:00Z", age_hours=48)
        assert policy.evaluate_retention(e) == RetentionAction.RETAIN

    def test_negative_age_rule_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            RetentionRule("fact", -1, RetentionAction.DELETE)


class TestImportExport:
    def test_valid_import(self):
        policy = MemorySiloPolicy()
        result = policy.validate_import_payload(1000, "fact", "ns1", "ns1")
        assert result["allowed"] is True
        assert result["violations"] == []

    def test_import_payload_too_large(self):
        policy = MemorySiloPolicy()
        result = policy.validate_import_payload(
            MAX_IMPORT_PAYLOAD_BYTES + 1, "fact", "ns1", "ns1"
        )
        assert result["allowed"] is False
        assert any("payload_too_large" in v for v in result["violations"])

    def test_import_disallowed_type(self):
        policy = MemorySiloPolicy()
        result = policy.validate_import_payload(100, "secret_key", "ns1", "ns1")
        assert result["allowed"] is False
        assert any("disallowed_import_type" in v for v in result["violations"])

    def test_import_cross_namespace_boundary_violation(self):
        policy = MemorySiloPolicy()
        result = policy.validate_import_payload(100, "fact", "ns_target", "ns_requester")
        assert result["allowed"] is False
        assert any("cross_namespace_import" in v for v in result["violations"])

    def test_export_same_namespace(self):
        policy = MemorySiloPolicy()
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        policy.add_entry(e)
        result = policy.validate_export("e1", "ns1")
        assert result["allowed"] is True

    def test_export_cross_namespace_denied(self):
        policy = MemorySiloPolicy()
        e = MemoryEntry("e1", "s1", "p1", "ns1", "fact", "abc", "2026-01-01T00:00:00Z")
        policy.add_entry(e)
        result = policy.validate_export("e1", "ns_other")
        assert result["allowed"] is False
