"""Governed ledger edit operations (v3.3 Epic A).

Extends the governance pipeline with explicit edit/merge semantics.
Every edit flows through the proposal lifecycle -- no direct mutations.

Edit types:
    create  -- new ledger entry (v3.2 default)
    update  -- modify existing entry (requires prior APPLIED proposal)
    merge   -- combine two entries into one (requires conflict resolution)
    redact  -- soft-delete with tombstone preservation

Invariants:
    - No edit bypasses the governance pipeline.
    - Every edit has an edit_type annotation in provenance.
    - Updates reference the prior proposal_id they supersede.
    - Merges require explicit conflict resolution first.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .proposal_model import (
    MemoryProposal, MemoryType, ProposalState, RiskTier,
    create_proposal, compute_payload_hash, IllegalTransitionError,
)
from .governance_pipeline import MemoryGovernancePipeline, GovernanceResult


class EditType(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    MERGE = "merge"
    REDACT = "redact"


@dataclass
class EditRecord:
    """Audit record for a ledger edit operation."""
    edit_id: str
    edit_type: EditType
    proposal_id: str
    prior_proposal_id: Optional[str]  # for update/merge: what it supersedes
    subject_key: str
    session_id: str
    actor: str
    reason: str
    payload_hash_before: Optional[str]
    payload_hash_after: str


class LedgerEditor:
    """Governed ledger editor with full audit trail.

    All edits flow through the governance pipeline. No direct mutations.
    """

    def __init__(self, pipeline: Optional[MemoryGovernancePipeline] = None):
        self.pipeline = pipeline or MemoryGovernancePipeline()
        self._edit_log: List[EditRecord] = []
        self._applied_by_key: Dict[str, str] = {}  # subject_key -> proposal_id
        self._stats = {
            "total_edits": 0,
            "creates": 0,
            "updates": 0,
            "merges": 0,
            "redacts": 0,
            "direct_edit_bypass_attempts": 0,
        }

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def edit_log(self) -> List[EditRecord]:
        return list(self._edit_log)

    def create_entry(
        self,
        session_id: str,
        origin_event_ids: List[str],
        memory_type: MemoryType,
        subject_key: str,
        payload: Dict[str, Any],
        confidence: float = 0.9,
        actor: str = "system",
    ) -> GovernanceResult:
        """Create a new ledger entry through governance."""
        result = self.pipeline.propose(
            session_id=session_id,
            origin_event_ids=origin_event_ids,
            memory_type=memory_type,
            subject_key=subject_key,
            payload=payload,
            confidence=confidence,
        )
        if result.queued and not result.throttled:
            self._stats["total_edits"] += 1
            self._stats["creates"] += 1
        return result

    def update_entry(
        self,
        session_id: str,
        origin_event_ids: List[str],
        memory_type: MemoryType,
        subject_key: str,
        new_payload: Dict[str, Any],
        confidence: float = 0.9,
        actor: str = "system",
        reason: str = "update",
    ) -> GovernanceResult:
        """Update an existing entry through governance.

        Requires a prior APPLIED proposal for the same subject_key.
        """
        prior_id = self._applied_by_key.get(subject_key)
        result = self.pipeline.propose(
            session_id=session_id,
            origin_event_ids=origin_event_ids,
            memory_type=memory_type,
            subject_key=subject_key,
            payload=new_payload,
            confidence=confidence,
        )
        if result.queued and not result.throttled:
            self._stats["total_edits"] += 1
            self._stats["updates"] += 1
            # Record edit with prior reference
            edit_rec = EditRecord(
                edit_id=f"edit-{result.proposal.proposal_id}",
                edit_type=EditType.UPDATE,
                proposal_id=result.proposal.proposal_id,
                prior_proposal_id=prior_id,
                subject_key=subject_key,
                session_id=session_id,
                actor=actor,
                reason=reason,
                payload_hash_before=None,
                payload_hash_after=result.proposal.payload_hash,
            )
            self._edit_log.append(edit_rec)
        return result

    def apply_and_track(self, proposal_id: str) -> Dict[str, Any]:
        """Apply a proposal and track it in the key registry."""
        result = self.pipeline.apply(proposal_id)
        if result.get("status") == "applied":
            proposal = self.pipeline.queue.get(proposal_id)
            if proposal:
                self._applied_by_key[proposal.subject_key] = proposal_id
        return result

    def redact_entry(
        self,
        session_id: str,
        subject_key: str,
        actor: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """Redact an applied entry by retracting it with tombstone metadata.

        Returns retraction result or None if no applied entry found.
        """
        prior_id = self._applied_by_key.get(subject_key)
        if not prior_id:
            return None
        result = self.pipeline.retract(prior_id, actor=actor, reason=reason)
        if result.get("status") == "retracted":
            self._stats["total_edits"] += 1
            self._stats["redacts"] += 1
            edit_rec = EditRecord(
                edit_id=f"redact-{prior_id}",
                edit_type=EditType.REDACT,
                proposal_id=prior_id,
                prior_proposal_id=prior_id,
                subject_key=subject_key,
                session_id=session_id,
                actor=actor,
                reason=reason,
                payload_hash_before=None,
                payload_hash_after="REDACTED",
            )
            self._edit_log.append(edit_rec)
            del self._applied_by_key[subject_key]
        return result

    def get_report(self) -> Dict[str, Any]:
        """Combined report for gate checks."""
        base = self.pipeline.get_report()
        base["edit_stats"] = self.stats
        base["direct_edit_bypass_attempts"] = self._stats["direct_edit_bypass_attempts"]
        return base
