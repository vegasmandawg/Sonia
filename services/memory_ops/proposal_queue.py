"""Bounded proposal queue with deterministic ordering and one-shot decisions.

Manages the lifecycle of memory proposals from submission through
approval/rejection to application or expiry.

Invariants:
    - Queue has a bounded capacity (MAX_PENDING).
    - Overflow produces explicit throttle, never silent drops.
    - One-shot approve/reject/retract: each decision can execute once.
    - Double-decision attempts are tracked and rejected.
    - Expired proposals cannot be approved.
    - Deterministic ordering by created_seq, tie-break by proposal_id.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from .proposal_model import (
    MemoryProposal,
    ProposalState,
    IllegalTransitionError,
    TERMINAL_STATES,
)
from .proposal_policy import PolicyDecision


MAX_PENDING_PROPOSALS = 50


class ProposalQueue:
    """Bounded, deterministic proposal queue with one-shot decision semantics."""

    def __init__(self, max_pending: int = MAX_PENDING_PROPOSALS):
        self._max_pending = max_pending
        self._proposals: OrderedDict[str, MemoryProposal] = OrderedDict()
        self._decisions: Dict[str, str] = {}   # proposal_id -> decision_state
        self._stats = {
            "total_submitted": 0,
            "total_approved": 0,
            "total_rejected": 0,
            "total_retracted": 0,
            "total_expired": 0,
            "total_applied": 0,
            "total_throttled": 0,
            "double_decision_attempts": 0,
            "illegal_transition_attempts": 0,
            "silent_write_count": 0,           # must always be 0
        }

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def pending_count(self) -> int:
        """Count of proposals in non-terminal, non-applied states."""
        return sum(
            1 for p in self._proposals.values()
            if p.state not in TERMINAL_STATES and not p.is_applied
        )

    @property
    def total_count(self) -> int:
        return len(self._proposals)

    def submit(
        self,
        proposal: MemoryProposal,
        policy: PolicyDecision,
    ) -> Tuple[Optional[MemoryProposal], Optional[str]]:
        """Submit a proposal to the queue.

        If auto_low tier: transitions directly to APPROVED.
        If guarded: transitions to PENDING_APPROVAL.
        If queue is at capacity: returns throttle reason.

        Returns (proposal_or_None, throttle_reason_or_None).
        """
        self._stats["total_submitted"] += 1

        # Check capacity for guarded proposals
        if policy.requires_approval and self.pending_count >= self._max_pending:
            self._stats["total_throttled"] += 1
            return None, "proposal_queue_at_capacity"

        # Store proposal
        self._proposals[proposal.proposal_id] = proposal

        # Route based on policy
        if not policy.requires_approval:
            # auto_low: PROPOSED -> APPROVED directly
            proposal.transition(
                ProposalState.APPROVED,
                actor="policy_auto",
                reason=policy.reason_code,
            )
            self._stats["total_approved"] += 1
            self._decisions[proposal.proposal_id] = ProposalState.APPROVED.value
        else:
            # guarded: PROPOSED -> PENDING_APPROVAL
            proposal.transition(
                ProposalState.PENDING_APPROVAL,
                actor="policy_gate",
                reason=policy.reason_code,
            )

        return proposal, None

    def approve(self, proposal_id: str, actor: str = "operator",
                reason: str = "") -> Dict[str, Any]:
        """Approve a pending proposal. One-shot: cannot re-approve.

        Returns result dict with status and details.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "reason": "proposal_not_found"}

        # Check for double-decision
        if proposal_id in self._decisions:
            self._stats["double_decision_attempts"] += 1
            return {
                "status": "error",
                "reason": "double_decision_rejected",
                "prior_decision": self._decisions[proposal_id],
            }

        # Check for expired
        if proposal.state == ProposalState.EXPIRED:
            return {"status": "error", "reason": "proposal_expired"}

        try:
            old_state = proposal.transition(
                ProposalState.APPROVED, actor=actor, reason=reason,
            )
        except IllegalTransitionError:
            self._stats["illegal_transition_attempts"] += 1
            return {
                "status": "error",
                "reason": "illegal_transition",
                "current_state": proposal.state.value,
            }

        self._stats["total_approved"] += 1
        self._decisions[proposal_id] = ProposalState.APPROVED.value
        return {
            "status": "approved",
            "proposal_id": proposal_id,
            "prior_state": old_state.value,
        }

    def reject(self, proposal_id: str, actor: str = "operator",
               reason: str = "") -> Dict[str, Any]:
        """Reject a pending proposal. One-shot: cannot re-reject."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "reason": "proposal_not_found"}

        if proposal_id in self._decisions:
            self._stats["double_decision_attempts"] += 1
            return {
                "status": "error",
                "reason": "double_decision_rejected",
                "prior_decision": self._decisions[proposal_id],
            }

        try:
            old_state = proposal.transition(
                ProposalState.REJECTED, actor=actor, reason=reason,
            )
        except IllegalTransitionError:
            self._stats["illegal_transition_attempts"] += 1
            return {
                "status": "error",
                "reason": "illegal_transition",
                "current_state": proposal.state.value,
            }

        self._stats["total_rejected"] += 1
        self._decisions[proposal_id] = ProposalState.REJECTED.value
        return {
            "status": "rejected",
            "proposal_id": proposal_id,
            "prior_state": old_state.value,
        }

    def apply(self, proposal_id: str) -> Dict[str, Any]:
        """Apply an approved proposal (mark as written to ledger).

        Only APPROVED proposals can be applied.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "reason": "proposal_not_found"}

        try:
            old_state = proposal.transition(
                ProposalState.APPLIED, actor="system", reason="ledger_write",
            )
        except IllegalTransitionError:
            self._stats["illegal_transition_attempts"] += 1
            return {
                "status": "error",
                "reason": "illegal_transition",
                "current_state": proposal.state.value,
            }

        self._stats["total_applied"] += 1
        return {
            "status": "applied",
            "proposal_id": proposal_id,
            "prior_state": old_state.value,
        }

    def retract(self, proposal_id: str, actor: str = "operator",
                reason: str = "") -> Dict[str, Any]:
        """Retract an applied proposal. Preserves append-only semantics."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "reason": "proposal_not_found"}

        try:
            old_state = proposal.transition(
                ProposalState.RETRACTED, actor=actor, reason=reason,
            )
        except IllegalTransitionError:
            self._stats["illegal_transition_attempts"] += 1
            return {
                "status": "error",
                "reason": "illegal_transition",
                "current_state": proposal.state.value,
            }

        self._stats["total_retracted"] += 1
        self._decisions[proposal_id] = ProposalState.RETRACTED.value
        return {
            "status": "retracted",
            "proposal_id": proposal_id,
            "prior_state": old_state.value,
        }

    def expire(self, proposal_id: str) -> Dict[str, Any]:
        """Expire a pending proposal (TTL exceeded or session ended)."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"status": "error", "reason": "proposal_not_found"}

        try:
            old_state = proposal.transition(
                ProposalState.EXPIRED, actor="system", reason="ttl_exceeded",
            )
        except IllegalTransitionError:
            self._stats["illegal_transition_attempts"] += 1
            return {
                "status": "error",
                "reason": "illegal_transition",
                "current_state": proposal.state.value,
            }

        self._stats["total_expired"] += 1
        self._decisions[proposal_id] = ProposalState.EXPIRED.value
        return {
            "status": "expired",
            "proposal_id": proposal_id,
            "prior_state": old_state.value,
        }

    def get(self, proposal_id: str) -> Optional[MemoryProposal]:
        return self._proposals.get(proposal_id)

    def list_pending(self) -> List[MemoryProposal]:
        """List proposals awaiting decision, ordered by created_seq."""
        pending = [
            p for p in self._proposals.values()
            if p.state == ProposalState.PENDING_APPROVAL
        ]
        return sorted(pending, key=lambda p: (p.created_seq, p.proposal_id))

    def list_approved(self) -> List[MemoryProposal]:
        """List approved proposals not yet applied."""
        return [
            p for p in self._proposals.values()
            if p.state == ProposalState.APPROVED
        ]

    def clear(self) -> None:
        self._proposals.clear()
        self._decisions.clear()
        self._stats = {k: 0 for k in self._stats}
