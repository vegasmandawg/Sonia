"""Memory Silo Policy — v4.2 E1.

Enforces memory namespace isolation with retention/deletion rules and
export/import boundary safety. Each memory entry is bound to a session
and persona namespace; cross-silo access is denied.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

SCHEMA_VERSION = "1.0.0"

# Maximum import payload size in bytes
MAX_IMPORT_PAYLOAD_BYTES = 1_048_576  # 1MB

# Allowed memory types for import
ALLOWED_IMPORT_TYPES = frozenset({"fact", "summary", "system_state", "user_preference"})


class RetentionAction(Enum):
    RETAIN = "retain"
    DELETE = "delete"
    ARCHIVE = "archive"


@dataclass(frozen=True)
class RetentionRule:
    """Immutable retention rule for a memory type."""
    memory_type: str
    max_age_hours: int
    action_on_expiry: RetentionAction

    def __post_init__(self):
        if self.max_age_hours < 0:
            raise ValueError("max_age_hours must be non-negative")
        if not self.memory_type:
            raise ValueError("memory_type must be non-empty")


@dataclass(frozen=True)
class MemoryEntry:
    """Immutable memory entry bound to session and persona namespace."""
    entry_id: str
    session_id: str
    persona_id: str
    namespace: str
    memory_type: str
    content_hash: str
    created_at: str  # ISO timestamp
    age_hours: float = 0.0

    def __post_init__(self):
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.session_id:
            raise ValueError("session_id must be non-empty")
        if not self.namespace:
            raise ValueError("namespace must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "entry_id": self.entry_id,
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "namespace": self.namespace,
            "memory_type": self.memory_type,
            "content_hash": self.content_hash,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class MemorySiloPolicy:
    """Enforces memory silo isolation, retention rules, and import/export boundaries."""

    def __init__(self):
        self._entries: Dict[str, MemoryEntry] = {}
        self._retention_rules: Dict[str, RetentionRule] = {}
        self._audit_log: List[dict] = []

    def add_entry(self, entry: MemoryEntry) -> None:
        self._entries[entry.entry_id] = entry

    def register_retention_rule(self, rule: RetentionRule) -> None:
        self._retention_rules[rule.memory_type] = rule

    def check_silo_access(self, requester_namespace: str, entry_id: str) -> bool:
        """Check if requester namespace can access a memory entry.

        Only the same namespace can access the entry.
        """
        entry = self._entries.get(entry_id)
        if not entry:
            self._audit_log.append({
                "action": "silo_access_denied",
                "reason": "entry_not_found",
                "entry_id": entry_id,
                "requester_namespace": requester_namespace,
            })
            return False

        allowed = entry.namespace == requester_namespace
        if not allowed:
            self._audit_log.append({
                "action": "silo_access_denied",
                "reason": "namespace_mismatch",
                "entry_id": entry_id,
                "requester_namespace": requester_namespace,
                "entry_namespace": entry.namespace,
            })
        return allowed

    def evaluate_retention(self, entry: MemoryEntry) -> RetentionAction:
        """Evaluate what retention action should be taken for a memory entry."""
        rule = self._retention_rules.get(entry.memory_type)
        if not rule:
            return RetentionAction.RETAIN  # no rule = retain

        if entry.age_hours > rule.max_age_hours:
            self._audit_log.append({
                "action": "retention_triggered",
                "entry_id": entry.entry_id,
                "memory_type": entry.memory_type,
                "age_hours": entry.age_hours,
                "max_age_hours": rule.max_age_hours,
                "result": rule.action_on_expiry.value,
            })
            return rule.action_on_expiry
        return RetentionAction.RETAIN

    def get_expired_entries(self) -> List[Tuple[MemoryEntry, RetentionAction]]:
        """Get all entries that have exceeded their retention rules."""
        results = []
        for entry in self._entries.values():
            action = self.evaluate_retention(entry)
            if action != RetentionAction.RETAIN:
                results.append((entry, action))
        return results

    def validate_import_payload(self, payload_bytes: int, memory_type: str,
                                 target_namespace: str, requester_namespace: str) -> dict:
        """Validate an import payload against boundary safety rules.

        Returns a dict with 'allowed' (bool) and 'violations' (list).
        """
        violations = []

        if payload_bytes > MAX_IMPORT_PAYLOAD_BYTES:
            violations.append(f"payload_too_large: {payload_bytes} > {MAX_IMPORT_PAYLOAD_BYTES}")

        if memory_type not in ALLOWED_IMPORT_TYPES:
            violations.append(f"disallowed_import_type: {memory_type}")

        if target_namespace != requester_namespace:
            violations.append(f"cross_namespace_import: {requester_namespace} -> {target_namespace}")

        allowed = len(violations) == 0
        result = {"allowed": allowed, "violations": violations}

        if not allowed:
            self._audit_log.append({
                "action": "import_rejected",
                "payload_bytes": payload_bytes,
                "memory_type": memory_type,
                "target_namespace": target_namespace,
                "requester_namespace": requester_namespace,
                "violations": violations,
            })

        return result

    def validate_export(self, entry_id: str, requester_namespace: str) -> dict:
        """Validate an export request. Only same-namespace exports allowed."""
        entry = self._entries.get(entry_id)
        if not entry:
            return {"allowed": False, "violations": ["entry_not_found"]}

        if entry.namespace != requester_namespace:
            self._audit_log.append({
                "action": "export_rejected",
                "entry_id": entry_id,
                "reason": "namespace_mismatch",
            })
            return {"allowed": False, "violations": ["cross_namespace_export"]}

        return {"allowed": True, "violations": []}

    @property
    def audit_log(self) -> List[dict]:
        return list(self._audit_log)

    @property
    def entry_count(self) -> int:
        return len(self._entries)
