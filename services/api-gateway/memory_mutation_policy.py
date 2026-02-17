"""Memory Mutation Policy — v4.2 E1.

Enforces authorization policies for memory mutations (create, update, delete)
and provides deterministic version conflict handling.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

SCHEMA_VERSION = "1.0.0"


class MutationType(Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ConflictResolution(Enum):
    LAST_WRITER_WINS = "last_writer_wins"
    REJECT = "reject"
    MERGE = "merge"


@dataclass(frozen=True)
class MutationGrant:
    """Immutable authorization grant for memory mutations."""
    grant_id: str
    persona_id: str
    session_id: str
    namespace: str
    allowed_mutations: FrozenSet[str]  # set of MutationType values
    allowed_memory_types: FrozenSet[str]

    def __post_init__(self):
        if not self.grant_id:
            raise ValueError("grant_id must be non-empty")
        if not self.persona_id:
            raise ValueError("persona_id must be non-empty")
        if not self.namespace:
            raise ValueError("namespace must be non-empty")
        if not self.allowed_mutations:
            raise ValueError("allowed_mutations must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "grant_id": self.grant_id,
            "persona_id": self.persona_id,
            "session_id": self.session_id,
            "namespace": self.namespace,
            "allowed_mutations": sorted(self.allowed_mutations),
            "allowed_memory_types": sorted(self.allowed_memory_types),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class VersionedEntry:
    """A versioned memory entry for conflict detection."""
    entry_id: str
    version: int
    content_hash: str
    namespace: str

    def __post_init__(self):
        if self.version < 0:
            raise ValueError("version must be non-negative")


class MemoryMutationPolicy:
    """Enforces mutation authorization and deterministic conflict handling."""

    def __init__(self, conflict_resolution: ConflictResolution = ConflictResolution.REJECT):
        self._grants: Dict[str, MutationGrant] = {}
        self._versions: Dict[str, VersionedEntry] = {}  # entry_id -> latest
        self._conflict_resolution = conflict_resolution
        self._audit_log: List[dict] = []

    def register_grant(self, grant: MutationGrant) -> None:
        self._grants[grant.grant_id] = grant

    def check_mutation(self, persona_id: str, session_id: str, namespace: str,
                       mutation_type: MutationType, memory_type: str) -> dict:
        """Check if a mutation is authorized.

        Returns dict with 'allowed' (bool), 'grant_id' (str or None), 'reason' (str).
        """
        for grant in self._grants.values():
            if (grant.persona_id == persona_id
                    and grant.session_id == session_id
                    and grant.namespace == namespace
                    and mutation_type.value in grant.allowed_mutations
                    and memory_type in grant.allowed_memory_types):
                return {
                    "allowed": True,
                    "grant_id": grant.grant_id,
                    "reason": "authorized_by_grant",
                }

        self._audit_log.append({
            "action": "mutation_denied",
            "persona_id": persona_id,
            "session_id": session_id,
            "namespace": namespace,
            "mutation_type": mutation_type.value,
            "memory_type": memory_type,
            "reason": "no_matching_grant",
        })
        return {
            "allowed": False,
            "grant_id": None,
            "reason": "no_matching_grant",
        }

    def register_version(self, entry: VersionedEntry) -> None:
        self._versions[entry.entry_id] = entry

    def check_version_conflict(self, entry_id: str, expected_version: int) -> dict:
        """Check for version conflicts deterministically.

        Returns dict with 'conflict' (bool), 'resolution' (str), 'current_version' (int).
        Resolution is always deterministic based on configured policy.
        """
        current = self._versions.get(entry_id)
        if not current:
            return {
                "conflict": False,
                "resolution": "no_existing_version",
                "current_version": None,
            }

        if current.version == expected_version:
            return {
                "conflict": False,
                "resolution": "version_match",
                "current_version": current.version,
            }

        # Conflict detected — resolution is deterministic
        resolution = self._conflict_resolution.value
        self._audit_log.append({
            "action": "version_conflict",
            "entry_id": entry_id,
            "expected_version": expected_version,
            "current_version": current.version,
            "resolution": resolution,
        })
        return {
            "conflict": True,
            "resolution": resolution,
            "current_version": current.version,
        }

    def resolve_conflict_deterministic(self, entry_id: str,
                                        incoming_version: int,
                                        incoming_hash: str) -> str:
        """Resolve a version conflict deterministically.

        Always returns the same resolution for the same inputs.
        With REJECT policy: always returns 'rejected'.
        With LAST_WRITER_WINS: always returns 'incoming_accepted'.
        With MERGE: always returns 'merge_required' (caller must merge).
        """
        if self._conflict_resolution == ConflictResolution.REJECT:
            return "rejected"
        elif self._conflict_resolution == ConflictResolution.LAST_WRITER_WINS:
            return "incoming_accepted"
        elif self._conflict_resolution == ConflictResolution.MERGE:
            return "merge_required"
        return "unknown_policy"

    @property
    def audit_log(self) -> List[dict]:
        return list(self._audit_log)

    @property
    def grant_count(self) -> int:
        return len(self._grants)
