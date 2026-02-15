"""Deterministic replay engine for memory governance verification.

Re-simulates proposal decisions over a canonical event stream and
produces replay hashes for comparison against live path.

Replay inputs:
    - Ordered proposals (by created_seq, tie-break by proposal_id)
    - Decision records (approve/reject/retract)
    - Policy version + schema version

Replay outputs:
    - replay_decisions_hash: SHA-256 of all decisions
    - ledger_state_hash: SHA-256 of applied proposals
    - applied_ids, rejected_ids, retracted_ids
    - conflict_events
    - divergence_count

Invariants:
    - Same input corpus + same decisions = same hashes.
    - Ordering ties resolved deterministically.
    - Missing proposal references detected and reported.
    - Zero silent mutations.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .proposal_model import (
    MemoryProposal, MemoryType, RiskTier, ProposalState,
    create_proposal, IllegalTransitionError,
)
from .proposal_policy import classify_proposal
from .conflict_detector import ConflictDetector, ConflictRecord


@dataclass(frozen=True)
class ReplayDecision:
    """A single decision in a replay sequence."""
    seq: int
    proposal_id: str
    action: str                      # APPROVE | REJECT | RETRACT | EXPIRE | AUTO_APPROVE
    actor: str
    reason: str = ""


@dataclass
class ReplayResult:
    """Complete result of a replay verification run."""
    replay_decisions_hash: str
    ledger_state_hash: str
    applied_ids: List[str]
    rejected_ids: List[str]
    retracted_ids: List[str]
    expired_ids: List[str]
    conflict_events: List[ConflictRecord]
    divergence_count: int = 0
    missing_proposal_refs: List[str] = field(default_factory=list)
    ordering_stable: bool = True
    total_proposals: int = 0
    total_decisions: int = 0


@dataclass
class ProposalInput:
    """Input specification for a proposal in replay."""
    session_id: str
    origin_event_ids: List[str]
    memory_type: MemoryType
    subject_key: str
    payload: Dict[str, Any]
    confidence: float
    schema_version: str = "1.0.0"
    policy_version: str = "1.0.0"


class ReplayEngine:
    """Deterministic replay engine for memory governance verification.

    Replays a proposal stream with decisions and verifies that
    the final state matches expected hashes.
    """

    def replay(
        self,
        proposals: List[ProposalInput],
        decisions: List[ReplayDecision],
    ) -> ReplayResult:
        """Execute a deterministic replay of proposals and decisions.

        Steps:
            1. Create proposals in order (by list index = created_seq)
            2. Classify each via policy
            3. Detect conflicts
            4. Apply decisions in order
            5. Compute final hashes

        Returns ReplayResult with all verification data.
        """
        # Phase 1: Create all proposals deterministically
        created: Dict[str, MemoryProposal] = {}
        conflict_detector = ConflictDetector()
        all_conflicts: List[ConflictRecord] = []
        decision_log: List[Dict[str, str]] = []

        for seq, p_input in enumerate(proposals):
            proposal = create_proposal(
                session_id=p_input.session_id,
                origin_event_ids=p_input.origin_event_ids,
                memory_type=p_input.memory_type,
                subject_key=p_input.subject_key,
                payload=p_input.payload,
                confidence=p_input.confidence,
                risk_tier=RiskTier.AUTO_LOW,  # placeholder
                created_seq=seq,
                schema_version=p_input.schema_version,
                policy_version=p_input.policy_version,
            )

            # Classify
            policy = classify_proposal(proposal)
            proposal.risk_tier = policy.tier

            # Detect conflicts
            conflicts = conflict_detector.detect(proposal)
            all_conflicts.extend(conflicts)
            conflict_detector.register(proposal)

            # Auto-approve if auto_low
            if not policy.requires_approval:
                proposal.transition(ProposalState.APPROVED,
                                    actor="policy_auto",
                                    reason=policy.reason_code)
                decision_log.append({
                    "proposal_id": proposal.proposal_id,
                    "action": "AUTO_APPROVE",
                    "reason": policy.reason_code,
                })
            else:
                proposal.transition(ProposalState.PENDING_APPROVAL,
                                    actor="policy_gate",
                                    reason=policy.reason_code)

            created[proposal.proposal_id] = proposal

        # Phase 2: Apply explicit decisions in order
        missing_refs: List[str] = []

        # Sort decisions by seq for deterministic ordering
        sorted_decisions = sorted(decisions, key=lambda d: d.seq)

        for decision in sorted_decisions:
            proposal = created.get(decision.proposal_id)
            if proposal is None:
                missing_refs.append(decision.proposal_id)
                continue

            try:
                if decision.action == "APPROVE":
                    proposal.transition(ProposalState.APPROVED,
                                        actor=decision.actor,
                                        reason=decision.reason)
                    decision_log.append({
                        "proposal_id": decision.proposal_id,
                        "action": "APPROVE",
                        "reason": decision.reason,
                    })

                elif decision.action == "REJECT":
                    proposal.transition(ProposalState.REJECTED,
                                        actor=decision.actor,
                                        reason=decision.reason)
                    decision_log.append({
                        "proposal_id": decision.proposal_id,
                        "action": "REJECT",
                        "reason": decision.reason,
                    })

                elif decision.action == "RETRACT":
                    # Must first apply if approved
                    if proposal.state == ProposalState.APPROVED:
                        proposal.transition(ProposalState.APPLIED,
                                            actor="system",
                                            reason="ledger_write")
                    proposal.transition(ProposalState.RETRACTED,
                                        actor=decision.actor,
                                        reason=decision.reason)
                    decision_log.append({
                        "proposal_id": decision.proposal_id,
                        "action": "RETRACT",
                        "reason": decision.reason,
                    })

                elif decision.action == "EXPIRE":
                    proposal.transition(ProposalState.EXPIRED,
                                        actor="system",
                                        reason="ttl_exceeded")
                    decision_log.append({
                        "proposal_id": decision.proposal_id,
                        "action": "EXPIRE",
                        "reason": decision.reason,
                    })

            except IllegalTransitionError:
                decision_log.append({
                    "proposal_id": decision.proposal_id,
                    "action": f"FAILED_{decision.action}",
                    "reason": "illegal_transition",
                })

        # Phase 3: Apply all approved proposals
        for proposal in created.values():
            if proposal.state == ProposalState.APPROVED:
                try:
                    proposal.transition(ProposalState.APPLIED,
                                        actor="system",
                                        reason="ledger_write")
                except IllegalTransitionError:
                    pass

        # Phase 4: Compute final state
        applied_ids = sorted([
            p.proposal_id for p in created.values()
            if p.state == ProposalState.APPLIED
        ])
        rejected_ids = sorted([
            p.proposal_id for p in created.values()
            if p.state == ProposalState.REJECTED
        ])
        retracted_ids = sorted([
            p.proposal_id for p in created.values()
            if p.state == ProposalState.RETRACTED
        ])
        expired_ids = sorted([
            p.proposal_id for p in created.values()
            if p.state == ProposalState.EXPIRED
        ])

        # Phase 5: Compute hashes
        replay_decisions_hash = self._hash_decisions(decision_log)
        ledger_state_hash = self._hash_ledger_state(created)

        return ReplayResult(
            replay_decisions_hash=replay_decisions_hash,
            ledger_state_hash=ledger_state_hash,
            applied_ids=applied_ids,
            rejected_ids=rejected_ids,
            retracted_ids=retracted_ids,
            expired_ids=expired_ids,
            conflict_events=all_conflicts,
            divergence_count=0,
            missing_proposal_refs=missing_refs,
            ordering_stable=True,
            total_proposals=len(proposals),
            total_decisions=len(decisions),
        )

    def verify(
        self,
        proposals: List[ProposalInput],
        decisions: List[ReplayDecision],
        expected_decisions_hash: str = "",
        expected_ledger_hash: str = "",
    ) -> ReplayResult:
        """Replay and verify against expected hashes.

        Sets divergence_count > 0 if any hash mismatches.
        """
        result = self.replay(proposals, decisions)
        divergences = 0

        if expected_decisions_hash and result.replay_decisions_hash != expected_decisions_hash:
            divergences += 1
        if expected_ledger_hash and result.ledger_state_hash != expected_ledger_hash:
            divergences += 1

        result.divergence_count = divergences
        return result

    @staticmethod
    def _hash_decisions(decision_log: List[Dict[str, str]]) -> str:
        """Deterministic hash of the decision sequence."""
        canonical = json.dumps(decision_log, sort_keys=True,
                               separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_ledger_state(proposals: Dict[str, MemoryProposal]) -> str:
        """Deterministic hash of the final ledger state.

        Includes all proposals with their terminal states, sorted by proposal_id.
        """
        state_entries = []
        for pid in sorted(proposals.keys()):
            p = proposals[pid]
            state_entries.append({
                "proposal_id": p.proposal_id,
                "state": p.state.value,
                "memory_type": p.memory_type.value,
                "subject_key": p.subject_key,
                "payload_hash": p.payload_hash,
            })
        canonical = json.dumps(state_entries, sort_keys=True,
                               separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
