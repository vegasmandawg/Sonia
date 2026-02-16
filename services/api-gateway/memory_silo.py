"""
v3.7 M1 — Memory Silo Enforcement

Persona-silo enforcement on retrieval and write operations.
Conflict-resolution policy for memory updates with deterministic precedence.
Ledger write reason codes and policy trace fields.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.memory_silo")


class ConflictResolution(str, Enum):
    """Deterministic precedence rules for memory update conflicts."""
    LAST_WRITE_WINS = "last_write_wins"
    FIRST_WRITE_WINS = "first_write_wins"
    HIGHER_PRIORITY_WINS = "higher_priority_wins"
    MANUAL_REVIEW = "manual_review"


# Priority ordering: higher number = higher priority
MEMORY_TYPE_PRIORITY: Dict[str, int] = {
    "turn_raw": 10,
    "turn_summary": 20,
    "vision_observation": 15,
    "tool_event": 25,
    "confirmation_event": 30,
    "system_state": 40,
    "user_fact": 50,
    "correction": 60,  # corrections always highest
}


@dataclass
class SiloPolicy:
    """Configuration for a persona's memory silo."""
    persona_id: str
    conflict_resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS
    max_entries_per_type: int = 1000
    allow_cross_persona_read: bool = False
    allowed_write_types: Optional[List[str]] = None  # None = all types allowed

    def allows_write_type(self, memory_type: str) -> bool:
        """Check if this silo policy permits the given write type."""
        if self.allowed_write_types is None:
            return True
        return memory_type in self.allowed_write_types


@dataclass
class LedgerEntry:
    """Immutable record of a memory mutation for audit."""
    entry_id: str
    timestamp: float
    session_id: str
    user_id: str
    persona_id: str
    operation: str  # "write", "read", "conflict_resolved"
    memory_type: str
    write_reason: str
    correlation_id: str = ""
    conflict_resolution: str = ""
    conflict_with: str = ""  # entry_id of conflicting record
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "persona_id": self.persona_id,
            "operation": self.operation,
            "memory_type": self.memory_type,
            "write_reason": self.write_reason,
            "correlation_id": self.correlation_id,
        }
        if self.conflict_resolution:
            d["conflict_resolution"] = self.conflict_resolution
        if self.conflict_with:
            d["conflict_with"] = self.conflict_with
        if self.metadata:
            d["metadata"] = self.metadata
        return d


class MemorySiloEnforcer:
    """
    Enforces persona-siloed memory access and provides deterministic
    conflict resolution for concurrent updates.

    Key invariants:
    1. Each persona's memory is isolated by persona_id tag.
    2. Cross-persona reads are blocked unless policy explicitly allows.
    3. Write conflicts are resolved by deterministic precedence rules.
    4. All mutations are recorded in an immutable ledger.
    """

    def __init__(self, default_resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS):
        self._silo_policies: Dict[str, SiloPolicy] = {}
        self._ledger: List[LedgerEntry] = []
        self._ledger_counter: int = 0
        self._max_ledger: int = 5000
        self._default_resolution = default_resolution

        # Register default persona silo
        self.register_silo(SiloPolicy(persona_id="default"))

    def register_silo(self, policy: SiloPolicy) -> None:
        """Register or update a persona silo policy."""
        self._silo_policies[policy.persona_id] = policy

    def get_silo_policy(self, persona_id: str) -> SiloPolicy:
        """Get silo policy, falling back to default."""
        return self._silo_policies.get(
            persona_id,
            self._silo_policies.get("default", SiloPolicy(persona_id=persona_id)),
        )

    def enforce_read(
        self,
        requesting_persona: str,
        target_persona: str,
    ) -> bool:
        """
        Check if requesting_persona can read target_persona's memories.

        Returns True if allowed.
        Raises ValueError if blocked.
        """
        if requesting_persona == target_persona:
            return True

        policy = self.get_silo_policy(requesting_persona)
        if policy.allow_cross_persona_read:
            return True

        raise ValueError(
            f"Cross-persona read blocked: persona '{requesting_persona}' "
            f"cannot read memories of persona '{target_persona}'"
        )

    def enforce_write(
        self,
        persona_id: str,
        memory_type: str,
        session_id: str,
        user_id: str,
        write_reason: str,
        correlation_id: str = "",
    ) -> LedgerEntry:
        """
        Validate a write operation against silo policy and create a ledger entry.

        Returns LedgerEntry on success.
        Raises ValueError if write is not permitted by silo policy.
        """
        policy = self.get_silo_policy(persona_id)

        if not policy.allows_write_type(memory_type):
            raise ValueError(
                f"Silo policy for persona '{persona_id}' does not allow "
                f"write type '{memory_type}'"
            )

        entry = self._create_ledger_entry(
            session_id=session_id,
            user_id=user_id,
            persona_id=persona_id,
            operation="write",
            memory_type=memory_type,
            write_reason=write_reason,
            correlation_id=correlation_id,
        )
        return entry

    def resolve_conflict(
        self,
        existing_entry: LedgerEntry,
        new_entry: LedgerEntry,
        resolution: Optional[ConflictResolution] = None,
    ) -> LedgerEntry:
        """
        Resolve a conflict between two memory operations using deterministic precedence.

        Returns the winning LedgerEntry.
        """
        res = resolution or self._default_resolution

        if res == ConflictResolution.LAST_WRITE_WINS:
            winner = new_entry
        elif res == ConflictResolution.FIRST_WRITE_WINS:
            winner = existing_entry
        elif res == ConflictResolution.HIGHER_PRIORITY_WINS:
            existing_prio = MEMORY_TYPE_PRIORITY.get(existing_entry.memory_type, 0)
            new_prio = MEMORY_TYPE_PRIORITY.get(new_entry.memory_type, 0)
            winner = new_entry if new_prio >= existing_prio else existing_entry
        else:
            # MANUAL_REVIEW: default to new entry but flag it
            winner = new_entry

        # Record conflict resolution in ledger
        resolution_entry = self._create_ledger_entry(
            session_id=winner.session_id,
            user_id=winner.user_id,
            persona_id=winner.persona_id,
            operation="conflict_resolved",
            memory_type=winner.memory_type,
            write_reason=winner.write_reason,
            correlation_id=winner.correlation_id,
            conflict_resolution=res.value,
            conflict_with=existing_entry.entry_id if winner is new_entry else new_entry.entry_id,
        )

        return winner

    def _create_ledger_entry(self, **kwargs) -> LedgerEntry:
        """Create and record an immutable ledger entry."""
        self._ledger_counter += 1
        entry = LedgerEntry(
            entry_id=f"le_{self._ledger_counter:06d}",
            timestamp=time.monotonic(),
            **kwargs,
        )
        self._ledger.append(entry)
        # Bounded ledger
        if len(self._ledger) > self._max_ledger:
            self._ledger = self._ledger[-self._max_ledger:]
        return entry

    def get_ledger(
        self,
        persona_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return recent ledger entries, optionally filtered by persona."""
        entries = self._ledger
        if persona_id:
            entries = [e for e in entries if e.persona_id == persona_id]
        return [e.to_dict() for e in entries[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """Return silo enforcement statistics."""
        return {
            "registered_personas": list(self._silo_policies.keys()),
            "persona_count": len(self._silo_policies),
            "ledger_entries": len(self._ledger),
            "ledger_counter": self._ledger_counter,
            "default_resolution": self._default_resolution.value,
        }
