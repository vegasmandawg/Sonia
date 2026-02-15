"""Memory governance pipeline orchestrator.

Wires proposal creation -> policy classification -> conflict detection ->
queue submission -> approval/reject/retract -> apply with full provenance.

This is the single entry point for memory mutations under governance.
No write path bypasses this pipeline.

Flow:
    1. Create canonical MemoryProposal
    2. Classify via PolicyDecision
    3. Detect conflicts against pending/committed
    4. Submit to bounded queue (auto-approve or gate)
    5. Await operator decision (approve/reject)
    6. Apply to ledger (mark APPLIED)
    7. Optionally retract (post-apply correction)

Every step emits provenance records.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .proposal_model import (
    MemoryProposal, MemoryType, RiskTier, ProposalState,
    create_proposal, IllegalTransitionError,
)
from .proposal_policy import classify_proposal, PolicyDecision
from .proposal_queue import ProposalQueue
from .conflict_detector import ConflictDetector, ConflictRecord
from .provenance import GovernanceProvenance


@dataclass
class GovernanceResult:
    """Result of processing a single memory mutation proposal."""
    proposal: MemoryProposal
    policy: PolicyDecision
    conflicts: List[ConflictRecord]
    queued: bool
    throttled: bool
    throttle_reason: Optional[str] = None
    auto_approved: bool = False


class MemoryGovernancePipeline:
    """Full memory governance pipeline with provenance.

    Flow: propose -> classify -> detect conflicts -> queue -> decide -> apply
    Every step emits provenance records.
    """

    def __init__(
        self,
        max_pending: int = 50,
        recency_window: int = 5,
    ):
        self.queue = ProposalQueue(max_pending=max_pending)
        self.conflicts = ConflictDetector(recency_window=recency_window)
        self.provenance = GovernanceProvenance()
        self._seq_counter = 0

    def _next_seq(self) -> int:
        seq = self._seq_counter
        self._seq_counter += 1
        return seq

    def propose(
        self,
        session_id: str,
        origin_event_ids: List[str],
        memory_type: MemoryType,
        subject_key: str,
        payload: Dict[str, Any],
        confidence: float = 0.9,
        schema_version: str = "1.0.0",
        policy_version: str = "1.0.0",
    ) -> GovernanceResult:
        """Submit a memory mutation proposal through the full governance pipeline.

        Steps:
            1. Create canonical proposal with deterministic identity
            2. Classify via policy (risk tier + approval requirements)
            3. Detect conflicts against pending/committed proposals
            4. Submit to queue (auto-approve for auto_low, gate for guarded)
            5. Record provenance at every step

        Returns GovernanceResult with all decisions.
        """
        seq = self._next_seq()

        # 1. Create proposal
        proposal = create_proposal(
            session_id=session_id,
            origin_event_ids=origin_event_ids,
            memory_type=memory_type,
            subject_key=subject_key,
            payload=payload,
            confidence=confidence,
            risk_tier=RiskTier.AUTO_LOW,  # placeholder, policy overrides
            created_seq=seq,
            schema_version=schema_version,
            policy_version=policy_version,
        )
        self.provenance.record_proposal_created(proposal)

        # 2. Classify
        policy = classify_proposal(proposal)
        proposal.risk_tier = policy.tier
        self.provenance.record_policy_classified(
            proposal.proposal_id, session_id, policy,
        )

        # 3. Detect conflicts
        detected_conflicts = self.conflicts.detect(proposal)
        for conflict in detected_conflicts:
            proposal.conflict_set_ids.append(conflict.conflict_id)
            self.provenance.record_conflict_detected(
                proposal.proposal_id, session_id, conflict,
            )

        # 4. Submit to queue
        queued_proposal, throttle_reason = self.queue.submit(proposal, policy)

        if throttle_reason:
            self.provenance.record_throttled(
                proposal.proposal_id, session_id, throttle_reason,
            )
            return GovernanceResult(
                proposal=proposal,
                policy=policy,
                conflicts=detected_conflicts,
                queued=False,
                throttled=True,
                throttle_reason=throttle_reason,
            )

        # Register for future conflict detection
        self.conflicts.register(proposal)

        # Record queue/approval provenance
        auto_approved = not policy.requires_approval
        if auto_approved:
            self.provenance.record_approved(
                proposal.proposal_id, session_id,
                actor="policy_auto", reason=policy.reason_code,
            )
        else:
            self.provenance.record_queued(
                proposal.proposal_id, session_id,
                queue_position=self.queue.pending_count,
            )

        return GovernanceResult(
            proposal=proposal,
            policy=policy,
            conflicts=detected_conflicts,
            queued=True,
            throttled=False,
            auto_approved=auto_approved,
        )

    def approve(self, proposal_id: str, actor: str = "operator",
                reason: str = "") -> Dict[str, Any]:
        """Approve a pending proposal."""
        result = self.queue.approve(proposal_id, actor, reason)
        proposal = self.queue.get(proposal_id)

        if result["status"] == "approved" and proposal:
            self.provenance.record_approved(
                proposal_id, proposal.session_id, actor, reason,
            )
        elif result.get("reason") == "illegal_transition" and proposal:
            self.provenance.record_illegal_transition(
                proposal_id, proposal.session_id,
                result.get("current_state", ""), "APPROVED",
            )

        return result

    def reject(self, proposal_id: str, actor: str = "operator",
               reason: str = "") -> Dict[str, Any]:
        """Reject a pending proposal."""
        result = self.queue.reject(proposal_id, actor, reason)
        proposal = self.queue.get(proposal_id)

        if result["status"] == "rejected" and proposal:
            self.provenance.record_rejected(
                proposal_id, proposal.session_id, actor, reason,
            )
        elif result.get("reason") == "illegal_transition" and proposal:
            self.provenance.record_illegal_transition(
                proposal_id, proposal.session_id,
                result.get("current_state", ""), "REJECTED",
            )

        return result

    def apply(self, proposal_id: str) -> Dict[str, Any]:
        """Apply an approved proposal to the ledger."""
        result = self.queue.apply(proposal_id)
        proposal = self.queue.get(proposal_id)

        if result["status"] == "applied" and proposal:
            self.provenance.record_applied(
                proposal_id, proposal.session_id,
            )

        return result

    def retract(self, proposal_id: str, actor: str = "operator",
                reason: str = "") -> Dict[str, Any]:
        """Retract an applied proposal."""
        result = self.queue.retract(proposal_id, actor, reason)
        proposal = self.queue.get(proposal_id)

        if result["status"] == "retracted" and proposal:
            self.provenance.record_retracted(
                proposal_id, proposal.session_id, actor, reason,
            )

        return result

    def expire(self, proposal_id: str) -> Dict[str, Any]:
        """Expire a pending proposal."""
        result = self.queue.expire(proposal_id)
        proposal = self.queue.get(proposal_id)

        if result["status"] == "expired" and proposal:
            self.provenance.record_expired(
                proposal_id, proposal.session_id,
            )

        return result

    def get_report(self) -> Dict[str, Any]:
        """Generate governance report for gate checks."""
        return {
            "queue_stats": self.queue.stats,
            "conflict_stats": self.conflicts.stats,
            "provenance_stats": self.provenance.stats,
            "provenance_hash": self.provenance.deterministic_hash(),
            "silent_write_count": self.provenance.silent_write_count(),
            "illegal_transition_attempts": self.queue.stats["illegal_transition_attempts"],
            "double_decision_attempts": self.queue.stats["double_decision_attempts"],
            "conflict_unsurfaced_count": self.conflicts.stats["conflict_unsurfaced_count"],
            "unresolved_conflicts": self.conflicts.unresolved_count,
        }

    def clear(self) -> None:
        self.queue.clear()
        self.conflicts.clear()
        self.provenance.clear()
        self._seq_counter = 0
