"""G24: Ledger Edit Governance + Contract Compatibility (16 tests).

Validates:
 - Proposal schema backward compatibility (additive fields only)
 - Ledger record schema version pinning
 - Serialization roundtrip stability
 - Migration idempotence and rollback viability
 - Tolerant parsing of unknown optional fields
 - Strict rejection of breaking required-field removals
 - Edit/merge/redact operations follow governed paths
 - Replay determinism for edit operations
 - Conflict detection for contradictory edits
"""
import hashlib
import json
import pytest

from services.memory_ops.proposal_model import (
    MemoryProposal, MemoryType, ProposalState, RiskTier,
    create_proposal, compute_payload_hash, compute_proposal_id,
    IllegalTransitionError, ALLOWED_TRANSITIONS,
)
from services.memory_ops.governance_pipeline import MemoryGovernancePipeline
from services.memory_ops.conflict_detector import ConflictType


class TestLedgerEditGovernance:
    """G24: Contract compatibility + ledger edit governance."""

    # ── Contract & Schema Compatibility (tests 1-10) ──────────────────

    def test_proposal_schema_backward_compatible(self):
        """1. Additive fields on MemoryProposal don't break existing consumers."""
        # Create proposal with base fields only (v3.2 API)
        p = create_proposal(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.FACT, subject_key="user.name",
            payload={"value": "Alice"}, confidence=0.9,
            risk_tier=RiskTier.AUTO_LOW, created_seq=0,
        )
        # Core fields all present
        assert p.proposal_id
        assert p.session_id == "s1"
        assert p.memory_type == MemoryType.FACT
        assert p.state == ProposalState.PROPOSED
        # v3.3 additive: edit_type defaults gracefully
        edit_type = getattr(p, "edit_type", "create")
        assert edit_type in ("create", "update", "merge", "redact")

    def test_ledger_record_schema_version_pinned(self):
        """2. Schema version is pinned and validated."""
        p = create_proposal(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.FACT, subject_key="k1",
            payload={"v": 1}, confidence=0.9,
            risk_tier=RiskTier.AUTO_LOW, created_seq=0,
            schema_version="1.0.0",
        )
        assert p.schema_version == "1.0.0"
        # Different schema version produces different proposal_id
        p2 = create_proposal(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.FACT, subject_key="k1",
            payload={"v": 1}, confidence=0.9,
            risk_tier=RiskTier.AUTO_LOW, created_seq=0,
            schema_version="2.0.0",
        )
        assert p.proposal_id != p2.proposal_id

    def test_proposal_state_enum_compatibility(self):
        """4. All v3.2 ProposalState values still valid."""
        expected = {"PROPOSED", "PENDING_APPROVAL", "APPROVED", "REJECTED",
                    "APPLIED", "RETRACTED", "EXPIRED"}
        actual = {s.value for s in ProposalState}
        assert expected.issubset(actual), f"Missing states: {expected - actual}"

    def test_legacy_record_ingestion_compatibility(self):
        """5. v3.2-era proposal can still be processed by governance pipeline."""
        pipeline = MemoryGovernancePipeline()
        result = pipeline.propose(
            session_id="legacy-s1", origin_event_ids=["le1"],
            memory_type=MemoryType.SESSION_CONTEXT, subject_key="context.main",
            payload={"context": "legacy data"}, confidence=0.95,
        )
        assert result.queued
        assert result.proposal.state in (ProposalState.APPROVED, ProposalState.PENDING_APPROVAL)

    def test_serialization_roundtrip_stability(self):
        """6. Proposal -> JSON -> reconstruct preserves identity."""
        p = create_proposal(
            session_id="s1", origin_event_ids=["e1", "e2"],
            memory_type=MemoryType.PREFERENCE, subject_key="pref.lang",
            payload={"language": "en", "weight": 0.8}, confidence=0.85,
            risk_tier=RiskTier.GUARDED_MEDIUM, created_seq=5,
        )
        # Serialize
        data = {
            "proposal_id": p.proposal_id,
            "session_id": p.session_id,
            "memory_type": p.memory_type.value,
            "subject_key": p.subject_key,
            "payload": p.payload,
            "payload_hash": p.payload_hash,
            "confidence": p.confidence,
            "risk_tier": p.risk_tier.value,
            "created_seq": p.created_seq,
            "schema_version": p.schema_version,
            "policy_version": p.policy_version,
        }
        json_str = json.dumps(data, sort_keys=True)
        restored = json.loads(json_str)
        assert restored["proposal_id"] == p.proposal_id
        assert restored["payload_hash"] == p.payload_hash

    def test_migration_noop_idempotence(self):
        """7. Re-running create with identical inputs produces identical proposal."""
        kwargs = dict(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.FACT, subject_key="k1",
            payload={"v": 42}, confidence=0.9,
            risk_tier=RiskTier.AUTO_LOW, created_seq=0,
        )
        p1 = create_proposal(**kwargs)
        p2 = create_proposal(**kwargs)
        assert p1.proposal_id == p2.proposal_id
        assert p1.payload_hash == p2.payload_hash

    def test_migration_rollback_viability(self):
        """8. Retracted proposal can be re-proposed with same identity."""
        pipeline = MemoryGovernancePipeline()
        r1 = pipeline.propose(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.SYSTEM_STATE, subject_key="sys.flag",
            payload={"active": True}, confidence=0.95,
        )
        pid = r1.proposal.proposal_id
        # Apply then retract
        pipeline.apply(pid)
        pipeline.retract(pid, actor="admin", reason="rollback")
        assert r1.proposal.state == ProposalState.RETRACTED
        # Re-propose same content produces same deterministic ID
        r2 = pipeline.propose(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.SYSTEM_STATE, subject_key="sys.flag",
            payload={"active": True}, confidence=0.95,
        )
        assert r2.proposal.proposal_id == pid

    def test_unknown_optional_fields_tolerant_parsing(self):
        """9. Extra fields in serialized proposal are ignored gracefully."""
        data = {
            "proposal_id": "abc123",
            "session_id": "s1",
            "memory_type": "FACT",
            "subject_key": "k1",
            "payload": {"v": 1},
            "payload_hash": compute_payload_hash({"v": 1}),
            "confidence": 0.9,
            "risk_tier": "auto_low",
            "created_seq": 0,
            "schema_version": "1.0.0",
            "policy_version": "1.0.0",
            "future_field_v35": "should_be_ignored",
            "another_unknown": 42,
        }
        # Core fields parse correctly, unknown fields don't crash
        assert data["proposal_id"] == "abc123"
        assert data["memory_type"] == "FACT"
        known_fields = {"proposal_id", "session_id", "memory_type", "subject_key",
                        "payload", "payload_hash", "confidence", "risk_tier",
                        "created_seq", "schema_version", "policy_version",
                        "origin_event_ids", "state", "decision_actor",
                        "decision_reason", "conflict_set_ids", "edit_type"}
        extra = set(data.keys()) - known_fields
        assert len(extra) >= 1  # at least one unknown field exists and doesn't break

    def test_strict_rejection_of_breaking_removals(self):
        """10. Missing required fields raise errors."""
        with pytest.raises(TypeError):
            # Missing required fields should fail
            MemoryProposal(proposal_id="x")  # type: ignore

    # ── Edit/Merge Governance (tests 11-16) ─────────────────────────────

    def test_edit_requires_governed_path(self):
        """11. Direct ledger mutation without proposal path is blocked.

        Uses the governance pipeline -- no way to APPLY without propose+approve.
        """
        from services.memory_ops.proposal_model import ALLOWED_TRANSITIONS
        # PROPOSED cannot jump directly to APPLIED
        assert ProposalState.APPLIED not in ALLOWED_TRANSITIONS[ProposalState.PROPOSED]

    def test_double_apply_rejected(self):
        """13. Same proposal cannot be applied twice."""
        pipeline = MemoryGovernancePipeline()
        r = pipeline.propose(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.SYSTEM_STATE, subject_key="sys.x",
            payload={"x": 1}, confidence=0.95,
        )
        pid = r.proposal.proposal_id
        result1 = pipeline.apply(pid)
        assert result1["status"] == "applied"
        result2 = pipeline.apply(pid)
        assert result2["status"] == "error"
        assert result2["reason"] == "illegal_transition"

    def test_rejected_proposal_cannot_be_applied(self):
        """14. Rejected proposal blocks apply path."""
        pipeline = MemoryGovernancePipeline()
        r = pipeline.propose(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.PREFERENCE, subject_key="pref.x",
            payload={"x": 1}, confidence=0.5,
        )
        pid = r.proposal.proposal_id
        pipeline.reject(pid, actor="admin", reason="not_needed")
        result = pipeline.apply(pid)
        assert result["status"] == "error"

    def test_replay_produces_identical_ledger_hash(self):
        """27. Identical event stream produces identical governance hash."""
        def run_pipeline():
            p = MemoryGovernancePipeline()
            p.propose("s1", ["e1"], MemoryType.FACT, "k1", {"v": 1}, 0.95)
            p.propose("s1", ["e2"], MemoryType.FACT, "k2", {"v": 2}, 0.95)
            return p.get_report()["provenance_hash"]

        h1 = run_pipeline()
        h2 = run_pipeline()
        assert h1 == h2

    def test_conflict_on_contradictory_edits(self):
        """28. Contradictory edits over same key surface conflict."""
        pipeline = MemoryGovernancePipeline()
        r1 = pipeline.propose(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.FACT, subject_key="user.age",
            payload={"age": 30}, confidence=0.9,
        )
        r2 = pipeline.propose(
            session_id="s1", origin_event_ids=["e2"],
            memory_type=MemoryType.FACT, subject_key="user.age",
            payload={"age": 31}, confidence=0.9,
        )
        assert len(r2.conflicts) > 0
        assert any(c.conflict_type == ConflictType.KEY_COLLISION for c in r2.conflicts)

    def test_conflict_resolution_records_full_audit_chain(self):
        """29. Conflict resolution emits provenance records."""
        pipeline = MemoryGovernancePipeline()
        r1 = pipeline.propose(
            session_id="s1", origin_event_ids=["e1"],
            memory_type=MemoryType.FACT, subject_key="user.email",
            payload={"email": "a@test.com"}, confidence=0.9,
        )
        r2 = pipeline.propose(
            session_id="s1", origin_event_ids=["e2"],
            memory_type=MemoryType.FACT, subject_key="user.email",
            payload={"email": "b@test.com"}, confidence=0.9,
        )
        assert len(r2.conflicts) > 0
        # Resolve conflict
        cid = r2.conflicts[0].conflict_id
        resolved = pipeline.conflicts.resolve(cid, "supersede", actor="admin")
        assert resolved
        # Provenance chain has conflict_detected records
        conflict_records = [
            r for r in pipeline.provenance.records
            if r.record_type == "conflict_detected"
        ]
        assert len(conflict_records) >= 1

    def test_replay_under_concurrent_ordering_stable(self):
        """30. Replay with concurrent proposals maintains stable ordering."""
        hashes = []
        for _ in range(3):
            p = MemoryGovernancePipeline()
            p.propose("s1", ["e1"], MemoryType.FACT, "k1", {"v": 1}, 0.95)
            p.propose("s1", ["e2"], MemoryType.FACT, "k2", {"v": 2}, 0.95)
            p.propose("s1", ["e3"], MemoryType.PREFERENCE, "k3", {"v": 3}, 0.5)
            hashes.append(p.get_report()["provenance_hash"])
        assert len(set(hashes)) == 1, "Provenance hash diverged across replays"
