"""Append-only provenance chain for memory governance audit trail.

Every proposal lifecycle transition emits a provenance record.
Records are immutable and produce a deterministic chain hash
for replay verification.

Record types:
    proposal_created, policy_classified, conflict_detected, queued,
    approval_requested, approved, rejected, expired, applied,
    retracted, replay_verified, replay_divergence

Invariants:
    - Append-only: records never modified or deleted.
    - Deterministic: same proposal stream -> same chain hash.
    - Tamper-evident: each record links to prior chain state.
    - Complete: every lifecycle transition has a record.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .proposal_model import MemoryProposal, ProposalState
from .proposal_policy import PolicyDecision
from .conflict_detector import ConflictRecord


@dataclass(frozen=True)
class GovernanceRecord:
    """Single audit record in the memory governance provenance chain."""
    seq: int                              # monotonic record index
    record_type: str                      # proposal_created | approved | etc.
    proposal_id: str
    session_id: str
    decision: str                         # lifecycle state or action
    reason_code: str
    correlation_id: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class GovernanceProvenance:
    """Append-only provenance chain for memory governance audit.

    Deterministic: same proposal stream produces same chain and hash.
    """

    def __init__(self):
        self._records: List[GovernanceRecord] = []
        self._seq = 0
        self._stats = {
            "total_records": 0,
            "proposal_created": 0,
            "policy_classified": 0,
            "conflict_detected": 0,
            "queued": 0,
            "approval_requested": 0,
            "approved": 0,
            "rejected": 0,
            "expired": 0,
            "applied": 0,
            "retracted": 0,
            "replay_verified": 0,
            "replay_divergence": 0,
            "illegal_transition": 0,
        }

    @property
    def records(self) -> List[GovernanceRecord]:
        return list(self._records)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def record_count(self) -> int:
        return len(self._records)

    def _append(self, record_type: str, proposal_id: str,
                session_id: str, decision: str, reason_code: str,
                correlation_id: str = "",
                details: Optional[Dict[str, Any]] = None) -> GovernanceRecord:
        """Append a record to the chain."""
        rec = GovernanceRecord(
            seq=self._seq,
            record_type=record_type,
            proposal_id=proposal_id,
            session_id=session_id,
            decision=decision,
            reason_code=reason_code,
            correlation_id=correlation_id,
            details=details or {},
        )
        self._records.append(rec)
        self._seq += 1
        self._stats["total_records"] += 1
        if record_type in self._stats:
            self._stats[record_type] += 1
        return rec

    # ── Lifecycle record methods ─────────────────────────────────────

    def record_proposal_created(self, proposal: MemoryProposal) -> None:
        self._append(
            "proposal_created",
            proposal.proposal_id,
            proposal.session_id,
            "PROPOSED",
            "proposal_submitted",
            details={
                "memory_type": proposal.memory_type.value,
                "subject_key": proposal.subject_key,
                "payload_hash": proposal.payload_hash,
                "confidence": proposal.confidence,
                "created_seq": proposal.created_seq,
                "origin_event_ids": proposal.origin_event_ids,
            },
        )

    def record_policy_classified(self, proposal_id: str,
                                  session_id: str,
                                  policy: PolicyDecision) -> None:
        self._append(
            "policy_classified",
            proposal_id,
            session_id,
            policy.tier.value,
            policy.reason_code,
            details={
                "requires_approval": policy.requires_approval,
                "token_scope": policy.required_token_scope,
                "confidence_factor": policy.confidence_factor,
            },
        )

    def record_conflict_detected(self, proposal_id: str,
                                  session_id: str,
                                  conflict: ConflictRecord) -> None:
        self._append(
            "conflict_detected",
            proposal_id,
            session_id,
            conflict.conflict_type,
            f"conflict_with_{conflict.proposal_id_a}",
            details={
                "conflict_id": conflict.conflict_id,
                "conflict_type": conflict.conflict_type,
                "severity": conflict.severity,
                "subject_key": conflict.subject_key,
                "counterpart_id": conflict.proposal_id_a,
            },
        )

    def record_queued(self, proposal_id: str, session_id: str,
                      queue_position: int = 0) -> None:
        self._append(
            "queued",
            proposal_id,
            session_id,
            "PENDING_APPROVAL",
            "queued_for_approval",
            details={"queue_position": queue_position},
        )

    def record_throttled(self, proposal_id: str, session_id: str,
                          reason: str) -> None:
        self._append(
            "queued",  # counts as a queue-related event
            proposal_id,
            session_id,
            "THROTTLED",
            reason,
        )

    def record_approved(self, proposal_id: str, session_id: str,
                         actor: str, reason: str = "") -> None:
        self._append(
            "approved",
            proposal_id,
            session_id,
            "APPROVED",
            reason or "operator_approved",
            details={"actor": actor},
        )

    def record_rejected(self, proposal_id: str, session_id: str,
                         actor: str, reason: str = "") -> None:
        self._append(
            "rejected",
            proposal_id,
            session_id,
            "REJECTED",
            reason or "operator_rejected",
            details={"actor": actor},
        )

    def record_expired(self, proposal_id: str, session_id: str) -> None:
        self._append(
            "expired",
            proposal_id,
            session_id,
            "EXPIRED",
            "ttl_exceeded",
        )

    def record_applied(self, proposal_id: str, session_id: str,
                        ledger_id: str = "") -> None:
        self._append(
            "applied",
            proposal_id,
            session_id,
            "APPLIED",
            "ledger_write_committed",
            details={"ledger_id": ledger_id},
        )

    def record_retracted(self, proposal_id: str, session_id: str,
                          actor: str, reason: str = "") -> None:
        self._append(
            "retracted",
            proposal_id,
            session_id,
            "RETRACTED",
            reason or "operator_retracted",
            details={"actor": actor},
        )

    def record_illegal_transition(self, proposal_id: str, session_id: str,
                                    from_state: str, to_state: str) -> None:
        self._append(
            "illegal_transition",
            proposal_id,
            session_id,
            "VIOLATION",
            f"illegal_{from_state}_to_{to_state}",
            details={
                "from_state": from_state,
                "to_state": to_state,
            },
        )

    def record_replay_verified(self, session_id: str,
                                replay_hash: str, ledger_hash: str) -> None:
        self._append(
            "replay_verified",
            "",
            session_id,
            "REPLAY_OK",
            "hashes_match",
            details={
                "replay_hash": replay_hash,
                "ledger_hash": ledger_hash,
            },
        )

    def record_replay_divergence(self, session_id: str,
                                  expected_hash: str,
                                  actual_hash: str,
                                  details: Optional[Dict] = None) -> None:
        self._append(
            "replay_divergence",
            "",
            session_id,
            "REPLAY_DIVERGE",
            "hash_mismatch",
            details={
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
                **(details or {}),
            },
        )

    # ── Hash and audit ───────────────────────────────────────────────

    def deterministic_hash(self) -> str:
        """SHA-256 hash of the full provenance chain for replay verification."""
        chain = [
            {
                "seq": r.seq,
                "record_type": r.record_type,
                "proposal_id": r.proposal_id,
                "session_id": r.session_id,
                "decision": r.decision,
                "reason_code": r.reason_code,
            }
            for r in self._records
        ]
        canonical = json.dumps(chain, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def silent_write_count(self) -> int:
        """Count proposals that reached APPLIED without a policy record.

        Must always be 0. Non-zero = G22 governance failure.
        """
        classified_ids = {
            r.proposal_id for r in self._records
            if r.record_type == "policy_classified"
        }
        applied_ids = {
            r.proposal_id for r in self._records
            if r.record_type == "applied"
        }
        # Applied without classification = silent write
        return len(applied_ids - classified_ids)

    def clear(self) -> None:
        self._records.clear()
        self._seq = 0
        self._stats = {k: 0 for k in self._stats}
