"""Canonical memory proposal model and governance state machine.

Every memory mutation flows through a MemoryProposal envelope with
deterministic identity, strict lifecycle transitions, and full provenance.

Invariants:
    - No silent writes: all mutations require a proposal/decision path.
    - Proposal identity is deterministic from stable fields only.
    - Illegal transitions are recorded, never silently absorbed.
    - Terminal states are immutable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Memory types (aligned with typed_memory.py subtypes) ─────────────

class MemoryType(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    EPISODE = "EPISODE"
    SYSTEM_STATE = "SYSTEM_STATE"
    SESSION_CONTEXT = "SESSION_CONTEXT"
    PROJECT = "PROJECT"


# ── Proposal lifecycle states ────────────────────────────────────────

class ProposalState(str, Enum):
    PROPOSED = "PROPOSED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    RETRACTED = "RETRACTED"
    EXPIRED = "EXPIRED"


# Terminal states: once entered, no further transitions allowed
TERMINAL_STATES = frozenset({
    ProposalState.REJECTED,
    ProposalState.EXPIRED,
    ProposalState.RETRACTED,
})

# States that mean "done successfully and written"
APPLIED_STATES = frozenset({ProposalState.APPLIED})


# ── Allowed transitions ─────────────────────────────────────────────

ALLOWED_TRANSITIONS: Dict[ProposalState, frozenset] = {
    ProposalState.PROPOSED: frozenset({
        ProposalState.PENDING_APPROVAL,   # guarded tier
        ProposalState.APPROVED,           # safe/auto_low tier only
    }),
    ProposalState.PENDING_APPROVAL: frozenset({
        ProposalState.APPROVED,
        ProposalState.REJECTED,
        ProposalState.EXPIRED,
    }),
    ProposalState.APPROVED: frozenset({
        ProposalState.APPLIED,
    }),
    ProposalState.APPLIED: frozenset({
        ProposalState.RETRACTED,
    }),
    # Terminal states: no outgoing transitions
    ProposalState.REJECTED: frozenset(),
    ProposalState.EXPIRED: frozenset(),
    ProposalState.RETRACTED: frozenset(),
}


# ── Risk tiers ───────────────────────────────────────────────────────

class RiskTier(str, Enum):
    AUTO_LOW = "auto_low"
    GUARDED_MEDIUM = "guarded_medium"
    GUARDED_HIGH = "guarded_high"


# ── Transition errors ────────────────────────────────────────────────

class IllegalTransitionError(Exception):
    """Raised when a proposal attempts an invalid state transition."""

    def __init__(self, proposal_id: str, from_state: ProposalState,
                 to_state: ProposalState):
        self.proposal_id = proposal_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Illegal transition: {proposal_id} "
            f"{from_state.value} -> {to_state.value}"
        )


# ── Canonical proposal envelope ──────────────────────────────────────

@dataclass
class MemoryProposal:
    """Canonical memory mutation proposal.

    Fields used for deterministic identity:
        session_id, memory_type, subject_key, payload_hash,
        schema_version, policy_version

    Mutable fields (lifecycle):
        state, decision_actor, decision_reason, conflict_set_ids
    """
    proposal_id: str                     # deterministic from proposal_key
    session_id: str
    origin_event_ids: List[str]          # voice/perception/tool refs
    memory_type: MemoryType
    subject_key: str                     # stable key for conflict checks
    payload: Dict[str, Any]
    payload_hash: str                    # SHA-256 of canonical payload
    confidence: float
    risk_tier: RiskTier
    created_seq: int                     # monotonic event index
    schema_version: str = "1.0.0"
    policy_version: str = "1.0.0"
    state: ProposalState = ProposalState.PROPOSED
    decision_actor: str = ""             # who approved/rejected/retracted
    decision_reason: str = ""
    conflict_set_ids: List[str] = field(default_factory=list)

    @property
    def proposal_key(self) -> str:
        """Deterministic identity tuple for dedup/replay."""
        parts = [
            self.session_id,
            self.memory_type.value,
            self.subject_key,
            self.payload_hash,
            self.schema_version,
            self.policy_version,
        ]
        return "|".join(parts)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def is_applied(self) -> bool:
        return self.state in APPLIED_STATES

    def transition(self, to_state: ProposalState, actor: str = "",
                   reason: str = "") -> ProposalState:
        """Attempt a state transition. Raises IllegalTransitionError on failure.

        Returns the new state on success.
        """
        allowed = ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if to_state not in allowed:
            raise IllegalTransitionError(self.proposal_id, self.state, to_state)

        old_state = self.state
        self.state = to_state
        if actor:
            self.decision_actor = actor
        if reason:
            self.decision_reason = reason
        return old_state


# ── Factory ──────────────────────────────────────────────────────────

def compute_payload_hash(payload: Dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of canonical payload JSON."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_proposal_id(session_id: str, memory_type: MemoryType,
                        subject_key: str, payload_hash: str,
                        schema_version: str = "1.0.0",
                        policy_version: str = "1.0.0") -> str:
    """Deterministic proposal ID from canonical fields."""
    parts = [session_id, memory_type.value, subject_key,
             payload_hash, schema_version, policy_version]
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def create_proposal(
    session_id: str,
    origin_event_ids: List[str],
    memory_type: MemoryType,
    subject_key: str,
    payload: Dict[str, Any],
    confidence: float,
    risk_tier: RiskTier,
    created_seq: int,
    schema_version: str = "1.0.0",
    policy_version: str = "1.0.0",
) -> MemoryProposal:
    """Create a new MemoryProposal with deterministic identity."""
    payload_hash = compute_payload_hash(payload)
    proposal_id = compute_proposal_id(
        session_id, memory_type, subject_key,
        payload_hash, schema_version, policy_version,
    )
    return MemoryProposal(
        proposal_id=proposal_id,
        session_id=session_id,
        origin_event_ids=list(origin_event_ids),
        memory_type=memory_type,
        subject_key=subject_key,
        payload=dict(payload),
        payload_hash=payload_hash,
        confidence=confidence,
        risk_tier=risk_tier,
        created_seq=created_seq,
        schema_version=schema_version,
        policy_version=policy_version,
    )
