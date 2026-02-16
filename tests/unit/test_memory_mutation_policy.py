"""Tests for memory_mutation_policy.py — v4.2 E1."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from memory_mutation_policy import (
    MutationGrant, MutationType, ConflictResolution,
    MemoryMutationPolicy, VersionedEntry,
)


class TestMutationGrant:
    def test_valid_grant(self):
        g = MutationGrant("g1", "p1", "s1", "ns1",
                          frozenset({"create", "update"}), frozenset({"fact"}))
        assert g.grant_id == "g1"
        assert g.fingerprint

    def test_empty_mutations_rejected(self):
        with pytest.raises(ValueError, match="allowed_mutations"):
            MutationGrant("g1", "p1", "s1", "ns1", frozenset(), frozenset({"fact"}))

    def test_fingerprint_deterministic(self):
        g1 = MutationGrant("g1", "p1", "s1", "ns1",
                           frozenset({"create"}), frozenset({"fact"}))
        g2 = MutationGrant("g1", "p1", "s1", "ns1",
                           frozenset({"create"}), frozenset({"fact"}))
        assert g1.fingerprint == g2.fingerprint


class TestMutationAuthorization:
    def test_authorized_mutation(self):
        policy = MemoryMutationPolicy()
        policy.register_grant(MutationGrant(
            "g1", "p1", "s1", "ns1",
            frozenset({"create", "update"}), frozenset({"fact", "summary"})
        ))
        result = policy.check_mutation("p1", "s1", "ns1", MutationType.CREATE, "fact")
        assert result["allowed"] is True
        assert result["grant_id"] == "g1"

    def test_mutation_without_grant_denied(self):
        policy = MemoryMutationPolicy()
        result = policy.check_mutation("p1", "s1", "ns1", MutationType.CREATE, "fact")
        assert result["allowed"] is False
        assert result["reason"] == "no_matching_grant"

    def test_wrong_mutation_type_denied(self):
        policy = MemoryMutationPolicy()
        policy.register_grant(MutationGrant(
            "g1", "p1", "s1", "ns1",
            frozenset({"create"}), frozenset({"fact"})
        ))
        result = policy.check_mutation("p1", "s1", "ns1", MutationType.DELETE, "fact")
        assert result["allowed"] is False

    def test_wrong_memory_type_denied(self):
        policy = MemoryMutationPolicy()
        policy.register_grant(MutationGrant(
            "g1", "p1", "s1", "ns1",
            frozenset({"create"}), frozenset({"fact"})
        ))
        result = policy.check_mutation("p1", "s1", "ns1", MutationType.CREATE, "secret")
        assert result["allowed"] is False

    def test_wrong_namespace_denied(self):
        policy = MemoryMutationPolicy()
        policy.register_grant(MutationGrant(
            "g1", "p1", "s1", "ns1",
            frozenset({"create"}), frozenset({"fact"})
        ))
        result = policy.check_mutation("p1", "s1", "ns_other", MutationType.CREATE, "fact")
        assert result["allowed"] is False


class TestVersionConflict:
    def test_no_conflict_when_version_matches(self):
        policy = MemoryMutationPolicy()
        policy.register_version(VersionedEntry("e1", 1, "abc", "ns1"))
        result = policy.check_version_conflict("e1", 1)
        assert result["conflict"] is False

    def test_conflict_detected_on_version_mismatch(self):
        policy = MemoryMutationPolicy()
        policy.register_version(VersionedEntry("e1", 2, "abc", "ns1"))
        result = policy.check_version_conflict("e1", 1)
        assert result["conflict"] is True
        assert result["resolution"] == "reject"  # default policy

    def test_conflict_resolution_deterministic(self):
        """Same inputs always produce same resolution."""
        p1 = MemoryMutationPolicy(ConflictResolution.REJECT)
        p2 = MemoryMutationPolicy(ConflictResolution.REJECT)
        p1.register_version(VersionedEntry("e1", 2, "abc", "ns1"))
        p2.register_version(VersionedEntry("e1", 2, "abc", "ns1"))
        r1 = p1.check_version_conflict("e1", 1)
        r2 = p2.check_version_conflict("e1", 1)
        assert r1["resolution"] == r2["resolution"]

    def test_last_writer_wins_resolution(self):
        policy = MemoryMutationPolicy(ConflictResolution.LAST_WRITER_WINS)
        assert policy.resolve_conflict_deterministic("e1", 2, "abc") == "incoming_accepted"

    def test_merge_resolution(self):
        policy = MemoryMutationPolicy(ConflictResolution.MERGE)
        assert policy.resolve_conflict_deterministic("e1", 2, "abc") == "merge_required"

    def test_negative_version_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            VersionedEntry("e1", -1, "abc", "ns1")
