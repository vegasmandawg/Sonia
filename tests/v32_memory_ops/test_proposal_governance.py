"""Memory proposal governance tests (G22).

Tests:
    1. No direct ledger write without proposal
    2. Proposal canonicalization stable
    3. Policy tier assignment deterministic
    4. Guarded tier requires approval token
    5. One-shot token cannot be reused
    6. Illegal state transitions fail closed
    7. Expired proposal cannot be approved
    8. Conflict detection: key collision surfaced
    9. Conflict resolution requires explicit choice
   10. Reject path writes no ledger mutation
   11. Apply path emits full provenance chain
   12. Retract path preserves append-only semantics
   13. Queue overflow: explicit throttle, no silent drop
   14. Idempotent approve call behavior
   15. Correlation ID propagation across records
   16. Policy reason codes emitted on every decision
"""
import pytest

from services.memory_ops.proposal_model import (
    MemoryProposal, MemoryType, RiskTier, ProposalState,
    create_proposal, compute_payload_hash, IllegalTransitionError,
    ALLOWED_TRANSITIONS, TERMINAL_STATES,
)
from services.memory_ops.proposal_policy import (
    classify_proposal, PolicyDecision,
)
from services.memory_ops.proposal_queue import ProposalQueue
from services.memory_ops.conflict_detector import (
    ConflictDetector, ConflictType, ResolutionChoice,
)
from services.memory_ops.provenance import GovernanceProvenance
from services.memory_ops.governance_pipeline import (
    MemoryGovernancePipeline, GovernanceResult,
)


# ── Helpers ──────────────────────────────────────────────────────────

SID = "gov-session"


def _propose(pipeline, subject_key="user.name", memory_type=MemoryType.FACT,
             payload=None, confidence=0.9):
    return pipeline.propose(
        session_id=SID,
        origin_event_ids=["evt-1"],
        memory_type=memory_type,
        subject_key=subject_key,
        payload=payload or {"subject": "user", "predicate": "name", "object": "Alice"},
        confidence=confidence,
    )


# ── Tests ────────────────────────────────────────────────────────────

class TestProposalGovernance:

    def test_no_direct_write_without_proposal(self):
        """Pipeline enforces that silent_write_count is always 0."""
        pipeline = MemoryGovernancePipeline()
        # Submit and approve a proposal through proper path
        result = _propose(pipeline)
        pipeline.approve(result.proposal.proposal_id)
        pipeline.apply(result.proposal.proposal_id)

        report = pipeline.get_report()
        assert report["silent_write_count"] == 0

    def test_proposal_canonicalization_stable(self):
        """Same inputs produce same proposal_id across runs."""
        ids = []
        for _ in range(3):
            p = create_proposal(
                "s1", ["e1"], MemoryType.FACT, "user.name",
                {"subject": "user", "predicate": "name", "object": "Alice"},
                0.9, RiskTier.GUARDED_MEDIUM, 1,
            )
            ids.append(p.proposal_id)
        assert len(set(ids)) == 1, "Same inputs must produce same proposal_id"

    def test_policy_tier_assignment_deterministic(self):
        """Same proposal always gets same policy decision."""
        p = create_proposal(
            "s1", ["e1"], MemoryType.FACT, "user.name",
            {"subject": "user"}, 0.9, RiskTier.AUTO_LOW, 1,
        )
        decisions = [classify_proposal(p) for _ in range(5)]
        tiers = {d.tier for d in decisions}
        reasons = {d.reason_code for d in decisions}
        assert len(tiers) == 1
        assert len(reasons) == 1

    def test_guarded_tier_requires_approval(self):
        """Guarded proposals go to PENDING_APPROVAL, not auto-approved."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline, memory_type=MemoryType.FACT, confidence=0.9)

        assert result.policy.requires_approval is True
        assert result.proposal.state == ProposalState.PENDING_APPROVAL
        assert result.auto_approved is False

    def test_one_shot_token_cannot_be_reused(self):
        """Approving the same proposal twice is rejected."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline)
        pid = result.proposal.proposal_id

        r1 = pipeline.approve(pid)
        assert r1["status"] == "approved"

        r2 = pipeline.approve(pid)
        assert r2["status"] == "error"
        assert r2["reason"] == "double_decision_rejected"
        assert pipeline.queue.stats["double_decision_attempts"] == 1

    def test_illegal_state_transitions_fail_closed(self):
        """Illegal transitions raise error and are tracked."""
        p = create_proposal(
            "s1", ["e1"], MemoryType.FACT, "k", {"a": 1},
            0.9, RiskTier.GUARDED_MEDIUM, 1,
        )
        p.transition(ProposalState.PENDING_APPROVAL)
        p.transition(ProposalState.REJECTED)

        with pytest.raises(IllegalTransitionError):
            p.transition(ProposalState.APPROVED)

    def test_expired_proposal_cannot_be_approved(self):
        """Expired proposals reject approval attempts."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline)
        pid = result.proposal.proposal_id

        pipeline.expire(pid)
        r = pipeline.approve(pid)
        assert r["status"] == "error"
        assert r["reason"] == "proposal_expired"

    def test_conflict_key_collision_surfaced(self):
        """Key collisions between proposals are detected and attached."""
        pipeline = MemoryGovernancePipeline()
        r1 = _propose(pipeline, subject_key="user.name",
                       payload={"subject": "user", "predicate": "name", "object": "Alice"})
        r2 = _propose(pipeline, subject_key="user.name",
                       payload={"subject": "user", "predicate": "name", "object": "Bob"})

        assert len(r2.conflicts) >= 1
        assert any(c.conflict_type == ConflictType.KEY_COLLISION for c in r2.conflicts)
        assert len(r2.proposal.conflict_set_ids) >= 1

    def test_conflict_resolution_requires_explicit_choice(self):
        """Unresolved conflicts are tracked; resolution requires explicit choice."""
        detector = ConflictDetector()
        p1 = create_proposal("s1", [], MemoryType.FACT, "k",
                              {"a": 1}, 0.9, RiskTier.GUARDED_MEDIUM, 1)
        p2 = create_proposal("s1", [], MemoryType.FACT, "k",
                              {"a": 2}, 0.9, RiskTier.GUARDED_MEDIUM, 2)
        detector.register(p1)
        conflicts = detector.detect(p2)

        assert len(conflicts) >= 1
        assert detector.unresolved_count >= 1

        # Resolve explicitly
        resolved = detector.resolve(conflicts[0].conflict_id,
                                     ResolutionChoice.SUPERSEDE, actor="operator")
        assert resolved is True
        assert detector.unresolved_count == 0

    def test_reject_path_writes_no_ledger_mutation(self):
        """Rejected proposals never reach APPLIED state."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline)
        pid = result.proposal.proposal_id

        pipeline.reject(pid, reason="not_needed")
        proposal = pipeline.queue.get(pid)

        assert proposal.state == ProposalState.REJECTED
        assert proposal.is_terminal is True
        assert proposal.is_applied is False
        assert pipeline.queue.stats["total_applied"] == 0

    def test_apply_path_emits_full_provenance_chain(self):
        """Applied proposal has complete provenance from creation to apply."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline)
        pid = result.proposal.proposal_id

        pipeline.approve(pid)
        pipeline.apply(pid)

        records = pipeline.provenance.records
        pid_records = [r for r in records if r.proposal_id == pid]
        record_types = [r.record_type for r in pid_records]

        assert "proposal_created" in record_types
        assert "policy_classified" in record_types
        assert "approved" in record_types
        assert "applied" in record_types

    def test_retract_preserves_append_only(self):
        """Retraction adds a record but doesn't delete the applied record."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline)
        pid = result.proposal.proposal_id

        pipeline.approve(pid)
        pipeline.apply(pid)
        records_before = len(pipeline.provenance.records)

        pipeline.retract(pid, reason="correction")
        records_after = len(pipeline.provenance.records)

        assert records_after > records_before
        proposal = pipeline.queue.get(pid)
        assert proposal.state == ProposalState.RETRACTED

        # Applied record still exists in provenance
        applied = [r for r in pipeline.provenance.records
                   if r.proposal_id == pid and r.record_type == "applied"]
        assert len(applied) == 1

    def test_queue_overflow_throttle_no_silent_drop(self):
        """Queue at capacity produces explicit throttle, never silent drop."""
        pipeline = MemoryGovernancePipeline(max_pending=3)

        results = []
        for i in range(5):
            r = _propose(pipeline, subject_key=f"key-{i}",
                          payload={"idx": i})
            results.append(r)

        throttled = [r for r in results if r.throttled]
        assert len(throttled) >= 1
        for t in throttled:
            assert t.throttle_reason == "proposal_queue_at_capacity"
        assert pipeline.queue.stats["silent_write_count"] == 0

    def test_idempotent_approve_double_decision(self):
        """Second approve on same proposal is cleanly rejected."""
        pipeline = MemoryGovernancePipeline()
        result = _propose(pipeline)
        pid = result.proposal.proposal_id

        r1 = pipeline.approve(pid)
        r2 = pipeline.approve(pid)

        assert r1["status"] == "approved"
        assert r2["status"] == "error"
        assert r2["reason"] == "double_decision_rejected"

    def test_correlation_propagation(self):
        """Origin event IDs propagate through provenance records."""
        pipeline = MemoryGovernancePipeline()
        result = pipeline.propose(
            session_id=SID,
            origin_event_ids=["vision-evt-42", "audio-evt-7"],
            memory_type=MemoryType.FACT,
            subject_key="scene.object",
            payload={"subject": "scene", "predicate": "contains", "object": "laptop"},
            confidence=0.9,
        )

        created_rec = [r for r in pipeline.provenance.records
                       if r.record_type == "proposal_created"][0]
        assert "vision-evt-42" in created_rec.details["origin_event_ids"]
        assert "audio-evt-7" in created_rec.details["origin_event_ids"]

    def test_policy_reason_codes_on_every_decision(self):
        """Every policy classification emits a non-empty reason_code."""
        pipeline = MemoryGovernancePipeline()

        # Submit varied types
        _propose(pipeline, memory_type=MemoryType.SYSTEM_STATE,
                 subject_key="health", payload={"component": "api"},
                 confidence=0.95)
        _propose(pipeline, memory_type=MemoryType.PREFERENCE,
                 subject_key="theme", payload={"key": "dark_mode"},
                 confidence=0.8)
        _propose(pipeline, memory_type=MemoryType.FACT,
                 subject_key="user.loc", payload={"city": "NYC"},
                 confidence=0.5)

        classified = [r for r in pipeline.provenance.records
                      if r.record_type == "policy_classified"]
        assert len(classified) == 3
        for rec in classified:
            assert rec.reason_code != ""
            assert len(rec.reason_code) > 3
