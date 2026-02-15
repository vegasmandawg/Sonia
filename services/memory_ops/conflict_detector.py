"""Conflict detection for memory proposals.

Detects semantic/key conflicts between pending and committed proposals.
Conflicts are surfaced explicitly — never auto-merged silently.

Conflict classes:
    KEY_COLLISION:    Same subject_key, divergent payload.
    TYPE_CONFLICT:    Same subject, different memory type precedence.
    RECENCY_CONFLICT: Competing proposals in the same sequence window.
    SCHEMA_CONFLICT:  Schema version mismatch on same subject_key.

Invariants:
    - Conflicts are detected and attached, never hidden.
    - No automatic merge: operator must choose resolution.
    - Conflict sets are deterministic (stable ordering).
    - Conflict detection is replay-stable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .proposal_model import MemoryProposal


# ── Conflict types ───────────────────────────────────────────────────

class ConflictType:
    KEY_COLLISION = "KEY_COLLISION"
    TYPE_CONFLICT = "TYPE_CONFLICT"
    RECENCY_CONFLICT = "RECENCY_CONFLICT"
    SCHEMA_CONFLICT = "SCHEMA_CONFLICT"


# ── Resolution choices ───────────────────────────────────────────────

class ResolutionChoice:
    SUPERSEDE = "supersede"          # new replaces old
    KEEP_EXISTING = "keep_existing"  # reject new, keep old
    COEXIST = "coexist"              # both valid
    REJECT = "reject"                # reject new outright


@dataclass(frozen=True)
class ConflictRecord:
    """A detected conflict between two proposals."""
    conflict_id: str                  # deterministic from both proposal IDs
    proposal_id_a: str                # existing/older proposal
    proposal_id_b: str                # new/incoming proposal
    conflict_type: str                # KEY_COLLISION | TYPE_CONFLICT | etc.
    severity: str                     # high | medium | low
    subject_key: str
    details: Dict[str, Any] = field(default_factory=dict)
    resolution: Optional[str] = None  # None until resolved


def _conflict_id(id_a: str, id_b: str, conflict_type: str) -> str:
    """Deterministic conflict ID from sorted proposal IDs and type."""
    parts = sorted([id_a, id_b]) + [conflict_type]
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class ConflictDetector:
    """Detects conflicts between a new proposal and existing proposals.

    Maintains a registry of known proposals for conflict scanning.
    All conflicts are explicit, deterministic, and never auto-resolved.
    """

    def __init__(self, recency_window: int = 5):
        self._registry: Dict[str, MemoryProposal] = {}
        self._conflicts: List[ConflictRecord] = []
        self._recency_window = recency_window
        self._stats = {
            "total_checked": 0,
            "total_conflicts_detected": 0,
            "key_collisions": 0,
            "type_conflicts": 0,
            "recency_conflicts": 0,
            "schema_conflicts": 0,
            "conflict_unsurfaced_count": 0,  # must always be 0
        }

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def conflicts(self) -> List[ConflictRecord]:
        return list(self._conflicts)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for c in self._conflicts if c.resolution is None)

    def register(self, proposal: MemoryProposal) -> None:
        """Register a proposal for future conflict checks."""
        self._registry[proposal.proposal_id] = proposal

    def detect(self, proposal: MemoryProposal) -> List[ConflictRecord]:
        """Detect conflicts between a new proposal and all registered proposals.

        Returns list of ConflictRecords (may be empty).
        Detected conflicts are appended to internal log.
        """
        self._stats["total_checked"] += 1
        found: List[ConflictRecord] = []

        for existing in self._registry.values():
            if existing.proposal_id == proposal.proposal_id:
                continue
            if existing.is_terminal:
                continue

            conflicts = self._check_pair(existing, proposal)
            found.extend(conflicts)

        for c in found:
            self._conflicts.append(c)
            self._stats["total_conflicts_detected"] += 1
            if c.conflict_type == ConflictType.KEY_COLLISION:
                self._stats["key_collisions"] += 1
            elif c.conflict_type == ConflictType.TYPE_CONFLICT:
                self._stats["type_conflicts"] += 1
            elif c.conflict_type == ConflictType.RECENCY_CONFLICT:
                self._stats["recency_conflicts"] += 1
            elif c.conflict_type == ConflictType.SCHEMA_CONFLICT:
                self._stats["schema_conflicts"] += 1

        return found

    def _check_pair(
        self,
        existing: MemoryProposal,
        incoming: MemoryProposal,
    ) -> List[ConflictRecord]:
        """Check a single pair for all conflict types."""
        results: List[ConflictRecord] = []

        # KEY_COLLISION: same subject_key, divergent payload
        if (existing.subject_key == incoming.subject_key
                and existing.memory_type == incoming.memory_type
                and existing.payload_hash != incoming.payload_hash):
            results.append(ConflictRecord(
                conflict_id=_conflict_id(
                    existing.proposal_id, incoming.proposal_id,
                    ConflictType.KEY_COLLISION,
                ),
                proposal_id_a=existing.proposal_id,
                proposal_id_b=incoming.proposal_id,
                conflict_type=ConflictType.KEY_COLLISION,
                severity="high",
                subject_key=existing.subject_key,
                details={
                    "existing_payload_hash": existing.payload_hash,
                    "incoming_payload_hash": incoming.payload_hash,
                },
            ))

        # TYPE_CONFLICT: same subject_key, different memory type
        if (existing.subject_key == incoming.subject_key
                and existing.memory_type != incoming.memory_type):
            results.append(ConflictRecord(
                conflict_id=_conflict_id(
                    existing.proposal_id, incoming.proposal_id,
                    ConflictType.TYPE_CONFLICT,
                ),
                proposal_id_a=existing.proposal_id,
                proposal_id_b=incoming.proposal_id,
                conflict_type=ConflictType.TYPE_CONFLICT,
                severity="medium",
                subject_key=existing.subject_key,
                details={
                    "existing_type": existing.memory_type.value,
                    "incoming_type": incoming.memory_type.value,
                },
            ))

        # RECENCY_CONFLICT: same subject_key within sequence window
        if (existing.subject_key == incoming.subject_key
                and existing.memory_type == incoming.memory_type
                and existing.payload_hash == incoming.payload_hash
                and abs(existing.created_seq - incoming.created_seq) <= self._recency_window):
            results.append(ConflictRecord(
                conflict_id=_conflict_id(
                    existing.proposal_id, incoming.proposal_id,
                    ConflictType.RECENCY_CONFLICT,
                ),
                proposal_id_a=existing.proposal_id,
                proposal_id_b=incoming.proposal_id,
                conflict_type=ConflictType.RECENCY_CONFLICT,
                severity="low",
                subject_key=existing.subject_key,
                details={
                    "existing_seq": existing.created_seq,
                    "incoming_seq": incoming.created_seq,
                    "window": self._recency_window,
                },
            ))

        # SCHEMA_CONFLICT: same subject_key, different schema version
        if (existing.subject_key == incoming.subject_key
                and existing.memory_type == incoming.memory_type
                and existing.schema_version != incoming.schema_version):
            results.append(ConflictRecord(
                conflict_id=_conflict_id(
                    existing.proposal_id, incoming.proposal_id,
                    ConflictType.SCHEMA_CONFLICT,
                ),
                proposal_id_a=existing.proposal_id,
                proposal_id_b=incoming.proposal_id,
                conflict_type=ConflictType.SCHEMA_CONFLICT,
                severity="medium",
                subject_key=existing.subject_key,
                details={
                    "existing_schema": existing.schema_version,
                    "incoming_schema": incoming.schema_version,
                },
            ))

        return results

    def resolve(self, conflict_id: str, choice: str,
                actor: str = "") -> bool:
        """Resolve a conflict with an explicit choice.

        Returns True if resolved, False if not found.
        """
        for i, c in enumerate(self._conflicts):
            if c.conflict_id == conflict_id:
                # Replace with resolved version (frozen dataclass)
                self._conflicts[i] = ConflictRecord(
                    conflict_id=c.conflict_id,
                    proposal_id_a=c.proposal_id_a,
                    proposal_id_b=c.proposal_id_b,
                    conflict_type=c.conflict_type,
                    severity=c.severity,
                    subject_key=c.subject_key,
                    details={**c.details, "resolved_by": actor},
                    resolution=choice,
                )
                return True
        return False

    def clear(self) -> None:
        self._registry.clear()
        self._conflicts.clear()
        self._stats = {k: 0 for k in self._stats}
