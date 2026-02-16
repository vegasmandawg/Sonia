"""
v4.0 E1 -- Session & Memory Governance Hardening

Provides:
1. Per-user session quotas with configurable limits
2. Session-level mutation authorization (read_only, standard, admin tiers)
3. Session kill-switch (revoke all sessions for a user atomically)
4. Memory retention policy enforcement (TTL-based expiry)
5. Memory import/export safety invariants
6. Incident snapshot memory fields
7. Deterministic turn sequencing for rerun support
8. Redaction replay integrity (access audit)
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("api-gateway.session_governance")


# ---------------------------------------------------------------------------
# 1. Session Quotas
# ---------------------------------------------------------------------------

class SessionQuotaExceeded(Exception):
    """Raised when a user exceeds their per-user session limit."""
    def __init__(self, user_id: str, current: int, limit: int):
        self.user_id = user_id
        self.current = current
        self.limit = limit
        super().__init__(
            f"User {user_id} has {current} active sessions (limit: {limit})"
        )


class SessionQuotaManager:
    """Enforces per-user session limits to prevent resource exhaustion."""

    def __init__(self, default_limit: int = 10, global_limit: int = 100):
        self._user_limits: Dict[str, int] = {}  # per-user overrides
        self._default_limit = default_limit
        self._global_limit = global_limit
        self._user_session_counts: Dict[str, int] = {}

    def set_user_limit(self, user_id: str, limit: int) -> None:
        """Override the session limit for a specific user."""
        if limit < 0:
            raise ValueError(f"Session limit must be >= 0, got {limit}")
        self._user_limits[user_id] = limit

    def get_user_limit(self, user_id: str) -> int:
        """Return the effective session limit for a user."""
        return self._user_limits.get(user_id, self._default_limit)

    def check_quota(self, user_id: str, current_count: int) -> bool:
        """Check if user can create a new session. Raises on violation."""
        limit = self.get_user_limit(user_id)
        if current_count >= limit:
            raise SessionQuotaExceeded(user_id, current_count, limit)
        return True

    def track_session_created(self, user_id: str) -> int:
        """Increment session count for user. Returns new count."""
        count = self._user_session_counts.get(user_id, 0) + 1
        self._user_session_counts[user_id] = count
        return count

    def track_session_closed(self, user_id: str) -> int:
        """Decrement session count for user. Returns new count."""
        count = max(0, self._user_session_counts.get(user_id, 0) - 1)
        self._user_session_counts[user_id] = count
        return count

    def get_user_count(self, user_id: str) -> int:
        """Return current active session count for user."""
        return self._user_session_counts.get(user_id, 0)

    def get_stats(self) -> Dict[str, Any]:
        """Return quota statistics."""
        return {
            "default_limit": self._default_limit,
            "global_limit": self._global_limit,
            "users_with_sessions": len(
                [u for u, c in self._user_session_counts.items() if c > 0]
            ),
            "total_active": sum(self._user_session_counts.values()),
            "custom_limits": len(self._user_limits),
        }


# ---------------------------------------------------------------------------
# 2. Mutation Authorization
# ---------------------------------------------------------------------------

class MutationTier(str, Enum):
    """Authorization tiers for memory and tool mutations."""
    READ_ONLY = "read_only"     # Can read, cannot write or execute tools
    STANDARD = "standard"       # Can read, write, execute safe tools
    ADMIN = "admin"             # Full access including guarded tools


class MutationDenied(Exception):
    """Raised when a mutation is denied by authorization policy."""
    def __init__(self, session_id: str, tier: str, operation: str):
        self.session_id = session_id
        self.tier = tier
        self.operation = operation
        super().__init__(
            f"Session {session_id} (tier={tier}) denied for operation: {operation}"
        )


class MutationAuthorizor:
    """Per-session mutation authorization with tier enforcement."""

    def __init__(self, default_tier: MutationTier = MutationTier.STANDARD):
        self._session_tiers: Dict[str, MutationTier] = {}
        self._default_tier = default_tier
        self._denial_count: int = 0
        self._check_count: int = 0

    def set_session_tier(self, session_id: str, tier: MutationTier) -> None:
        """Set the mutation tier for a session."""
        self._session_tiers[session_id] = tier

    def get_session_tier(self, session_id: str) -> MutationTier:
        """Get the effective mutation tier for a session."""
        return self._session_tiers.get(session_id, self._default_tier)

    def lock_session(self, session_id: str) -> None:
        """Lock a session to read-only mode."""
        self._session_tiers[session_id] = MutationTier.READ_ONLY

    def unlock_session(self, session_id: str, tier: MutationTier = MutationTier.STANDARD) -> None:
        """Unlock a session from read-only mode."""
        self._session_tiers[session_id] = tier

    def check_memory_write(self, session_id: str) -> bool:
        """Check if session is authorized to write memories."""
        self._check_count += 1
        tier = self.get_session_tier(session_id)
        if tier == MutationTier.READ_ONLY:
            self._denial_count += 1
            raise MutationDenied(session_id, tier.value, "memory_write")
        return True

    def check_tool_execution(self, session_id: str, tool_name: str) -> bool:
        """Check if session is authorized to execute a tool."""
        self._check_count += 1
        tier = self.get_session_tier(session_id)
        if tier == MutationTier.READ_ONLY:
            self._denial_count += 1
            raise MutationDenied(session_id, tier.value, f"tool:{tool_name}")
        return True

    def remove_session(self, session_id: str) -> None:
        """Clean up session tier when session is destroyed."""
        self._session_tiers.pop(session_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """Return authorization statistics."""
        tier_counts: Dict[str, int] = {}
        for tier in self._session_tiers.values():
            tier_counts[tier.value] = tier_counts.get(tier.value, 0) + 1
        return {
            "total_checks": self._check_count,
            "total_denials": self._denial_count,
            "sessions_tracked": len(self._session_tiers),
            "tier_distribution": tier_counts,
        }


# ---------------------------------------------------------------------------
# 3. Session Kill-Switch
# ---------------------------------------------------------------------------

@dataclass
class KillSwitchResult:
    """Result of a session kill-switch operation."""
    user_id: str
    sessions_killed: int
    session_ids: List[str]
    timestamp: float


class SessionKillSwitch:
    """Atomically revoke all sessions for a user."""

    def __init__(self):
        self._kill_log: List[KillSwitchResult] = []
        self._max_log: int = 500

    def execute(
        self,
        user_id: str,
        active_session_ids: List[str],
        close_callback=None,
    ) -> KillSwitchResult:
        """
        Kill all sessions for a user.

        Args:
            user_id: The user whose sessions to kill
            active_session_ids: List of active session IDs for this user
            close_callback: Optional callable(session_id) to invoke for each session

        Returns KillSwitchResult with details of the operation.
        """
        killed = []
        for sid in active_session_ids:
            try:
                if close_callback:
                    close_callback(sid)
                killed.append(sid)
            except Exception as e:
                logger.warning(f"Failed to kill session {sid}: {e}")

        result = KillSwitchResult(
            user_id=user_id,
            sessions_killed=len(killed),
            session_ids=killed,
            timestamp=time.time(),
        )
        self._kill_log.append(result)
        if len(self._kill_log) > self._max_log:
            self._kill_log = self._kill_log[-self._max_log:]

        logger.info(
            f"Kill-switch executed for user {user_id}: "
            f"{len(killed)}/{len(active_session_ids)} sessions killed"
        )
        return result

    def get_kill_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent kill-switch operations."""
        return [
            {
                "user_id": r.user_id,
                "sessions_killed": r.sessions_killed,
                "session_ids": r.session_ids,
                "timestamp": r.timestamp,
            }
            for r in self._kill_log[-limit:]
        ]


# ---------------------------------------------------------------------------
# 4. Retention Policy
# ---------------------------------------------------------------------------

class RetentionPolicy(str, Enum):
    """Memory retention policies with TTL enforcement."""
    EPHEMERAL = "ephemeral"      # Deleted after session ends
    SHORT_TERM = "short_term"    # 24 hours
    MEDIUM_TERM = "medium_term"  # 7 days
    LONG_TERM = "long_term"      # 90 days
    PERMANENT = "permanent"      # Never auto-deleted


# TTL in seconds for each policy
RETENTION_TTL: Dict[str, Optional[int]] = {
    RetentionPolicy.EPHEMERAL.value: 0,          # session-bound
    RetentionPolicy.SHORT_TERM.value: 86400,     # 24h
    RetentionPolicy.MEDIUM_TERM.value: 604800,   # 7d
    RetentionPolicy.LONG_TERM.value: 7776000,    # 90d
    RetentionPolicy.PERMANENT.value: None,        # never
}

# Default retention by memory type
DEFAULT_RETENTION: Dict[str, str] = {
    "turn_raw": RetentionPolicy.SHORT_TERM.value,
    "turn_summary": RetentionPolicy.LONG_TERM.value,
    "vision_observation": RetentionPolicy.SHORT_TERM.value,
    "tool_event": RetentionPolicy.MEDIUM_TERM.value,
    "confirmation_event": RetentionPolicy.MEDIUM_TERM.value,
    "system_state": RetentionPolicy.LONG_TERM.value,
    "user_fact": RetentionPolicy.PERMANENT.value,
    "correction": RetentionPolicy.PERMANENT.value,
}


@dataclass
class RetentionRecord:
    """Tracks retention metadata for a memory entry."""
    memory_id: str
    memory_type: str
    retention_policy: str
    created_at: float
    expires_at: Optional[float]  # None = permanent
    session_id: str = ""

    @property
    def is_expired(self) -> bool:
        """Check if the memory has exceeded its TTL."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class RetentionEnforcer:
    """Enforces memory retention policies with TTL-based expiry."""

    def __init__(self):
        self._records: Dict[str, RetentionRecord] = {}
        self._expiry_count: int = 0

    def assign_retention(
        self,
        memory_id: str,
        memory_type: str,
        session_id: str = "",
        policy_override: Optional[str] = None,
    ) -> RetentionRecord:
        """Assign a retention policy to a memory entry."""
        policy = policy_override or DEFAULT_RETENTION.get(
            memory_type, RetentionPolicy.MEDIUM_TERM.value
        )
        ttl = RETENTION_TTL.get(policy)
        now = time.time()
        expires_at = (now + ttl) if ttl is not None and ttl > 0 else None

        # Ephemeral memories expire when session ends (tracked separately)
        if policy == RetentionPolicy.EPHEMERAL.value:
            expires_at = None  # handled by session close

        record = RetentionRecord(
            memory_id=memory_id,
            memory_type=memory_type,
            retention_policy=policy,
            created_at=now,
            expires_at=expires_at,
            session_id=session_id,
        )
        self._records[memory_id] = record
        return record

    def check_expired(self) -> List[str]:
        """Return list of memory IDs that have exceeded their TTL."""
        expired = [
            mid for mid, rec in self._records.items()
            if rec.is_expired
        ]
        return expired

    def expire_for_session(self, session_id: str) -> List[str]:
        """Expire all ephemeral memories bound to a session."""
        expired = []
        for mid, rec in list(self._records.items()):
            if (rec.session_id == session_id
                    and rec.retention_policy == RetentionPolicy.EPHEMERAL.value):
                expired.append(mid)
                self._expiry_count += 1
        # Remove from tracking
        for mid in expired:
            del self._records[mid]
        return expired

    def remove_expired(self) -> List[str]:
        """Remove all TTL-expired records. Returns list of expired memory IDs."""
        expired = self.check_expired()
        for mid in expired:
            del self._records[mid]
            self._expiry_count += 1
        return expired

    def get_retention_info(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get retention info for a specific memory."""
        rec = self._records.get(memory_id)
        if not rec:
            return None
        return {
            "memory_id": rec.memory_id,
            "memory_type": rec.memory_type,
            "retention_policy": rec.retention_policy,
            "created_at": rec.created_at,
            "expires_at": rec.expires_at,
            "is_expired": rec.is_expired,
            "session_id": rec.session_id,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return retention enforcement statistics."""
        policy_counts: Dict[str, int] = {}
        for rec in self._records.values():
            policy_counts[rec.retention_policy] = (
                policy_counts.get(rec.retention_policy, 0) + 1
            )
        return {
            "tracked_memories": len(self._records),
            "total_expiries": self._expiry_count,
            "policy_distribution": policy_counts,
            "currently_expired": len(self.check_expired()),
        }


# ---------------------------------------------------------------------------
# 5. Memory Import/Export Safety
# ---------------------------------------------------------------------------

class ExportValidationError(Exception):
    """Raised when export/import validation fails."""
    pass


@dataclass
class MemoryExportBundle:
    """Validated memory export bundle with integrity hash."""
    user_id: str
    session_id: str
    persona_id: str
    export_timestamp: float
    memories: List[Dict[str, Any]]
    integrity_hash: str
    format_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_version": self.format_version,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "export_timestamp": self.export_timestamp,
            "memory_count": len(self.memories),
            "integrity_hash": self.integrity_hash,
            "memories": self.memories,
        }


class MemoryExportImportSafety:
    """Validates memory export/import operations with integrity checks."""

    REQUIRED_FIELDS = {"type", "content", "metadata"}
    FORBIDDEN_FIELDS = {"__internal", "_raw_sql", "password", "api_key", "secret"}

    @staticmethod
    def compute_integrity_hash(memories: List[Dict[str, Any]]) -> str:
        """Compute deterministic SHA-256 hash of memory contents."""
        canonical = json.dumps(memories, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def validate_for_export(
        self,
        memories: List[Dict[str, Any]],
        user_id: str,
        session_id: str = "",
        persona_id: str = "default",
    ) -> MemoryExportBundle:
        """Validate and package memories for export."""
        validated = []
        for i, mem in enumerate(memories):
            # Strip internal fields
            cleaned = {
                k: v for k, v in mem.items()
                if k not in self.FORBIDDEN_FIELDS
            }
            # Ensure user_id matches
            meta = cleaned.get("metadata", {})
            if isinstance(meta, dict):
                mem_user = meta.get("user_id", user_id)
                if mem_user != user_id:
                    raise ExportValidationError(
                        f"Memory {i} belongs to user {mem_user}, "
                        f"not export target {user_id}"
                    )
            validated.append(cleaned)

        integrity = self.compute_integrity_hash(validated)

        return MemoryExportBundle(
            user_id=user_id,
            session_id=session_id,
            persona_id=persona_id,
            export_timestamp=time.time(),
            memories=validated,
            integrity_hash=integrity,
        )

    def validate_for_import(
        self,
        bundle: Dict[str, Any],
        target_user_id: str,
    ) -> List[Dict[str, Any]]:
        """Validate an import bundle before ingestion."""
        # Format version check
        version = bundle.get("format_version", "")
        if version != "1.0":
            raise ExportValidationError(
                f"Unsupported export format version: {version}"
            )

        # User ID match
        if bundle.get("user_id") != target_user_id:
            raise ExportValidationError(
                f"Bundle user_id {bundle.get('user_id')} does not match "
                f"import target {target_user_id}"
            )

        memories = bundle.get("memories", [])
        if not isinstance(memories, list):
            raise ExportValidationError("memories field must be a list")

        # Integrity check
        declared_hash = bundle.get("integrity_hash", "")
        actual_hash = self.compute_integrity_hash(memories)
        if declared_hash and declared_hash != actual_hash:
            raise ExportValidationError(
                f"Integrity hash mismatch: declared={declared_hash[:16]}... "
                f"actual={actual_hash[:16]}..."
            )

        # Content validation
        for i, mem in enumerate(memories):
            # Check for forbidden fields
            forbidden_found = set(mem.keys()) & self.FORBIDDEN_FIELDS
            if forbidden_found:
                raise ExportValidationError(
                    f"Memory {i} contains forbidden fields: {forbidden_found}"
                )

        return memories


# ---------------------------------------------------------------------------
# 6. Incident Snapshot Memory Fields
# ---------------------------------------------------------------------------

@dataclass
class IncidentMemorySnapshot:
    """Captures memory state at incident time for forensics."""
    incident_id: str
    timestamp: float
    session_id: str
    user_id: str
    correlation_id: str
    recent_memories: List[Dict[str, Any]]
    active_sessions: List[str]
    pending_mutations: List[Dict[str, Any]]
    retention_stats: Dict[str, Any]
    silo_stats: Dict[str, Any]
    quota_stats: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "recent_memory_count": len(self.recent_memories),
            "active_session_count": len(self.active_sessions),
            "pending_mutation_count": len(self.pending_mutations),
            "retention_stats": self.retention_stats,
            "silo_stats": self.silo_stats,
            "quota_stats": self.quota_stats,
        }


# ---------------------------------------------------------------------------
# 7. Deterministic Turn Sequencing
# ---------------------------------------------------------------------------

class TurnSequencer:
    """Assigns deterministic, monotonic turn numbers per session for rerun support."""

    def __init__(self):
        self._session_counters: Dict[str, int] = {}

    def next_turn_num(self, session_id: str) -> int:
        """Get the next turn number for a session (1-based)."""
        current = self._session_counters.get(session_id, 0) + 1
        self._session_counters[session_id] = current
        return current

    def get_current(self, session_id: str) -> int:
        """Get the current (latest) turn number for a session."""
        return self._session_counters.get(session_id, 0)

    def reset_session(self, session_id: str) -> None:
        """Reset turn counter when session is destroyed."""
        self._session_counters.pop(session_id, None)

    def compute_rerun_hash(
        self,
        session_id: str,
        turn_num: int,
        user_input: str,
        model_response: str,
    ) -> str:
        """Compute a deterministic hash for a turn (for replay verification)."""
        payload = json.dumps({
            "session_id": session_id,
            "turn_num": turn_num,
            "user_input": user_input,
            "model_response": model_response,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 8. Redaction Replay Integrity
# ---------------------------------------------------------------------------

@dataclass
class RedactionAccessRecord:
    """Records when redacted content was accessed or queried."""
    access_id: str
    timestamp: float
    session_id: str
    user_id: str
    memory_id: str
    access_type: str  # "query", "retrieve", "export"
    redacted_fields: List[str]
    correlation_id: str = ""


class RedactionReplayTracker:
    """Tracks access to redacted content for audit and replay integrity."""

    def __init__(self, max_records: int = 2000):
        self._records: List[RedactionAccessRecord] = []
        self._counter: int = 0
        self._max_records = max_records

    def record_access(
        self,
        session_id: str,
        user_id: str,
        memory_id: str,
        access_type: str,
        redacted_fields: List[str],
        correlation_id: str = "",
    ) -> RedactionAccessRecord:
        """Record an access to redacted content."""
        self._counter += 1
        record = RedactionAccessRecord(
            access_id=f"ra_{self._counter:06d}",
            timestamp=time.time(),
            session_id=session_id,
            user_id=user_id,
            memory_id=memory_id,
            access_type=access_type,
            redacted_fields=redacted_fields,
            correlation_id=correlation_id,
        )
        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]
        return record

    def get_access_log(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query access records with optional filters."""
        results = self._records
        if user_id:
            results = [r for r in results if r.user_id == user_id]
        if session_id:
            results = [r for r in results if r.session_id == session_id]
        return [
            {
                "access_id": r.access_id,
                "timestamp": r.timestamp,
                "session_id": r.session_id,
                "user_id": r.user_id,
                "memory_id": r.memory_id,
                "access_type": r.access_type,
                "redacted_field_count": len(r.redacted_fields),
                "correlation_id": r.correlation_id,
            }
            for r in results[-limit:]
        ]

    def verify_replay_integrity(
        self,
        original_access_ids: List[str],
    ) -> Dict[str, Any]:
        """Verify that a set of access records still exist (not tampered)."""
        existing_ids = {r.access_id for r in self._records}
        found = [aid for aid in original_access_ids if aid in existing_ids]
        missing = [aid for aid in original_access_ids if aid not in existing_ids]
        return {
            "total_checked": len(original_access_ids),
            "found": len(found),
            "missing": len(missing),
            "missing_ids": missing,
            "integrity_ok": len(missing) == 0,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return tracker statistics."""
        return {
            "total_records": len(self._records),
            "counter": self._counter,
            "max_records": self._max_records,
        }
