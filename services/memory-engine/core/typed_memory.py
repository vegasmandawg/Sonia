"""
Typed Memory Model — SONIA v3.0.0 Milestone 3

Provides:
  - MemorySubtype enum (FACT, PREFERENCE, PROJECT, SESSION_CONTEXT, SYSTEM_STATE)
  - Pydantic schemas per subtype with identity keys for conflict detection
  - TypedMemoryValidator: schema validation + temporal invariant checks
  - ConflictDetector: identity-key based overlap detection
  - VersionChainManager: immutable version chains with optimistic concurrency
  - RedactionManager: governance-audited redaction / unredaction
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("memory-engine.typed_memory")

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class MemorySubtype(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    PROJECT = "PROJECT"
    SESSION_CONTEXT = "SESSION_CONTEXT"
    SYSTEM_STATE = "SYSTEM_STATE"


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas (one per subtype)
# ─────────────────────────────────────────────────────────────────────────────

class FactSchema(BaseModel):
    subject: str
    predicate: str
    object: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Optional[str] = None


class PreferenceSchema(BaseModel):
    category: str
    key: str
    value: str
    priority: float = Field(default=5.0, ge=0.0, le=10.0)


class ProjectSchema(BaseModel):
    project_id: str
    context_type: str
    summary: str
    tags: List[str] = Field(default_factory=list)


class SessionContextSchema(BaseModel):
    session_id: str
    context_key: str
    context_value: str
    ttl_seconds: Optional[int] = None


class SystemStateSchema(BaseModel):
    component: str
    state_key: str
    state_value: str
    health_status: Optional[str] = None


SUBTYPE_SCHEMAS = {
    MemorySubtype.FACT: FactSchema,
    MemorySubtype.PREFERENCE: PreferenceSchema,
    MemorySubtype.PROJECT: ProjectSchema,
    MemorySubtype.SESSION_CONTEXT: SessionContextSchema,
    MemorySubtype.SYSTEM_STATE: SystemStateSchema,
}

SCHEMA_VERSIONS = {
    MemorySubtype.FACT: "FACT:v1",
    MemorySubtype.PREFERENCE: "PREFERENCE:v1",
    MemorySubtype.PROJECT: "PROJECT:v1",
    MemorySubtype.SESSION_CONTEXT: "SESSION_CONTEXT:v1",
    MemorySubtype.SYSTEM_STATE: "SYSTEM_STATE:v1",
}

# ─────────────────────────────────────────────────────────────────────────────
# Timestamp helpers — ISO 8601 UTC strict
# ─────────────────────────────────────────────────────────────────────────────

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
)


def _validate_iso_utc(ts: Optional[str], field_name: str) -> Optional[str]:
    """Validate ISO 8601 UTC timestamp. Returns normalised value or raises."""
    if ts is None:
        return None
    if not _ISO_RE.match(ts):
        raise ValueError(f"{field_name} must be ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ), got: {ts}")
    # Parse to ensure it's actually valid
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        raise ValueError(f"{field_name} is not a valid datetime: {ts}")
    return ts


def utc_now_iso() -> str:
    """Current UTC time as ISO 8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────────────────────
# TypedMemoryValidator
# ─────────────────────────────────────────────────────────────────────────────

class TypedMemoryValidator:
    """Validate typed memory content against schema + temporal invariants."""

    def validate(
        self,
        subtype: str,
        content_json: str,
        metadata: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns {"valid": bool, "errors": [...], "parsed": <model|None>}
        """
        errors: List[str] = []

        # Subtype check
        try:
            sub = MemorySubtype(subtype)
        except ValueError:
            return {"valid": False, "errors": [f"Unknown subtype: {subtype}"], "parsed": None}

        # Parse JSON content
        try:
            if isinstance(content_json, str):
                content_dict = json.loads(content_json)
            else:
                content_dict = content_json
        except (json.JSONDecodeError, TypeError) as exc:
            return {"valid": False, "errors": [f"Invalid JSON content: {exc}"], "parsed": None}

        # Schema validation
        schema_cls = SUBTYPE_SCHEMAS[sub]
        try:
            parsed = schema_cls(**content_dict)
        except Exception as exc:
            return {"valid": False, "errors": [f"Schema validation failed: {exc}"], "parsed": None}

        # Temporal invariants
        try:
            _validate_iso_utc(valid_from, "valid_from")
        except ValueError as exc:
            errors.append(str(exc))

        try:
            _validate_iso_utc(valid_until, "valid_until")
        except ValueError as exc:
            errors.append(str(exc))

        if valid_from and valid_until:
            if valid_until <= valid_from:
                errors.append("valid_until must be strictly after valid_from")

        if errors:
            return {"valid": False, "errors": errors, "parsed": None}

        return {"valid": True, "errors": [], "parsed": parsed}

    def get_schema_version(self, subtype: str) -> str:
        sub = MemorySubtype(subtype)
        return SCHEMA_VERSIONS[sub]


# ─────────────────────────────────────────────────────────────────────────────
# ConflictDetector
# ─────────────────────────────────────────────────────────────────────────────

class ConflictDetector:
    """Detect identity-key conflicts for FACT and PREFERENCE subtypes."""

    def detect_conflicts(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        subtype: str,
        content: Dict[str, Any],
        valid_from: Optional[str],
        valid_until: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Detect conflicts with existing current (non-superseded, non-redacted) memories.
        Returns list of conflict dicts. Inserts conflict records into memory_conflicts.
        """
        sub = MemorySubtype(subtype)
        conflicts: List[Dict[str, Any]] = []

        if sub == MemorySubtype.FACT:
            conflicts = self._detect_fact_conflicts(conn, memory_id, content, valid_from, valid_until)
        elif sub == MemorySubtype.PREFERENCE:
            conflicts = self._detect_preference_conflicts(conn, memory_id, content)

        # Insert conflict records
        now = utc_now_iso()
        for c in conflicts:
            conflict_id = f"conflict_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """INSERT INTO memory_conflicts
                   (conflict_id, memory_id_a, memory_id_b, conflict_type, severity, detected_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    conflict_id,
                    c["memory_id_a"],
                    c["memory_id_b"],
                    c["conflict_type"],
                    c.get("severity", "medium"),
                    now,
                    json.dumps(c.get("metadata", {})),
                ),
            )
            c["conflict_id"] = conflict_id

        return conflicts

    def _detect_fact_conflicts(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        content: Dict[str, Any],
        valid_from: Optional[str],
        valid_until: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        FACT conflicts: same (subject, predicate), overlapping time windows,
        different object, both confidence > 0.5.
        """
        subject = content.get("subject", "")
        predicate = content.get("predicate", "")
        obj = content.get("object", "")
        confidence = content.get("confidence", 1.0)

        if confidence <= 0.5:
            return []

        # Find current facts with same identity key
        rows = conn.execute(
            """SELECT id, content, valid_from, valid_until
               FROM ledger
               WHERE memory_subtype = 'FACT'
                 AND superseded_by IS NULL
                 AND redacted = 0
                 AND content_format = 'json'
                 AND id != ?""",
            (memory_id,),
        ).fetchall()

        conflicts = []
        for row in rows:
            try:
                existing = json.loads(row["content"])
            except (json.JSONDecodeError, TypeError):
                continue

            # Same identity key?
            if existing.get("subject") != subject or existing.get("predicate") != predicate:
                continue

            # Same object = consistent, no conflict
            if existing.get("object") == obj:
                continue

            # Existing confidence check
            if existing.get("confidence", 1.0) <= 0.5:
                continue

            # Temporal overlap check
            # If either side has NULL bounds, skip overlap check (untimed observation)
            existing_from = row["valid_from"]
            existing_until = row["valid_until"]

            if valid_from is None and valid_until is None:
                # New memory is untimed — skip overlap check but still conflict
                pass
            elif existing_from is None and existing_until is None:
                # Existing is untimed — skip overlap check but still conflict
                pass
            else:
                # Both have temporal bounds — check overlap
                if not self._overlaps(valid_from, valid_until, existing_from, existing_until):
                    continue

            conflicts.append({
                "memory_id_a": memory_id,
                "memory_id_b": row["id"],
                "conflict_type": "FACT_CONTRADICTION",
                "severity": "high",
                "metadata": {
                    "identity_key": f"{subject}:{predicate}",
                    "new_object": obj,
                    "existing_object": existing.get("object"),
                },
            })

        return conflicts

    def _detect_preference_conflicts(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        content: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        PREFERENCE conflicts: same (category, key), different value, both current.
        """
        category = content.get("category", "")
        key = content.get("key", "")
        value = content.get("value", "")

        rows = conn.execute(
            """SELECT id, content
               FROM ledger
               WHERE memory_subtype = 'PREFERENCE'
                 AND superseded_by IS NULL
                 AND redacted = 0
                 AND content_format = 'json'
                 AND id != ?""",
            (memory_id,),
        ).fetchall()

        conflicts = []
        for row in rows:
            try:
                existing = json.loads(row["content"])
            except (json.JSONDecodeError, TypeError):
                continue

            if existing.get("category") != category or existing.get("key") != key:
                continue

            # Same value = not a conflict (duplicate / consistent)
            if existing.get("value") == value:
                continue

            conflicts.append({
                "memory_id_a": memory_id,
                "memory_id_b": row["id"],
                "conflict_type": "PREFERENCE_CONFLICT",
                "severity": "medium",
                "metadata": {
                    "identity_key": f"{category}:{key}",
                    "new_value": value,
                    "existing_value": existing.get("value"),
                },
            })

        return conflicts

    @staticmethod
    def _overlaps(
        from_a: Optional[str], until_a: Optional[str],
        from_b: Optional[str], until_b: Optional[str],
    ) -> bool:
        """Check if two temporal ranges overlap. Open-ended (None) = unbounded."""
        # [from_a, until_a) overlaps [from_b, until_b)?
        # If either end is None, it's unbounded in that direction.
        a_start = from_a or ""
        b_start = from_b or ""
        a_end = until_a or "9999-12-31T23:59:59Z"
        b_end = until_b or "9999-12-31T23:59:59Z"
        return a_start < b_end and b_start < a_end


# ─────────────────────────────────────────────────────────────────────────────
# VersionChainManager
# ─────────────────────────────────────────────────────────────────────────────

class ConflictError(Exception):
    """Raised when optimistic concurrency check fails on supersede."""
    pass


class VersionChainManager:
    """Manages immutable version chains with optimistic concurrency."""

    def create_version(
        self,
        conn: sqlite3.Connection,
        original_id: str,
        new_content: str,
        metadata: Optional[str],
        memory_type: str,
        subtype: str,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
    ) -> str:
        """
        Create a new version superseding original_id.
        Uses optimistic concurrency: UPDATE ... WHERE superseded_by IS NULL.
        If rowcount=0, raises ConflictError (someone else already superseded).
        """
        now = utc_now_iso()
        new_id = f"mem_{uuid.uuid4().hex[:12]}"

        # Get the chain head from the original
        orig_row = conn.execute(
            "SELECT version_chain_head, validation_schema, content_format FROM ledger WHERE id = ?",
            (original_id,),
        ).fetchone()

        if orig_row is None:
            raise ValueError(f"Original memory not found: {original_id}")

        chain_head = orig_row["version_chain_head"] or original_id
        validation_schema = orig_row["validation_schema"]
        content_format = orig_row["content_format"] or "json"

        # Insert new version FIRST (before updating FK on original)
        conn.execute(
            """INSERT INTO ledger
               (id, type, content, metadata, created_at, updated_at,
                memory_subtype, valid_from, valid_until, recorded_at,
                superseded_by, version_chain_head, redacted,
                validation_schema, content_format)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, ?, ?)""",
            (
                new_id, memory_type, new_content, metadata, now, now,
                subtype, valid_from, valid_until, now,
                chain_head, validation_schema, content_format,
            ),
        )

        # Optimistic concurrency: mark original as superseded
        cursor = conn.execute(
            "UPDATE ledger SET superseded_by = ?, updated_at = ? WHERE id = ? AND superseded_by IS NULL",
            (new_id, now, original_id),
        )
        if cursor.rowcount == 0:
            # Rollback the insert — someone else already superseded
            conn.execute("DELETE FROM ledger WHERE id = ?", (new_id,))
            raise ConflictError(
                f"Memory {original_id} already superseded (concurrent update)"
            )

        return new_id

    def get_version_history(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
    ) -> List[Dict[str, Any]]:
        """Get ordered version history for a memory (by recorded_at ASC)."""
        # First find the chain head
        row = conn.execute(
            "SELECT version_chain_head FROM ledger WHERE id = ?",
            (memory_id,),
        ).fetchone()

        if row is None:
            return []

        chain_head = row["version_chain_head"] or memory_id

        rows = conn.execute(
            """SELECT id, type, content, metadata, created_at, updated_at,
                      memory_subtype, valid_from, valid_until, recorded_at,
                      superseded_by, version_chain_head, redacted,
                      validation_schema, content_format
               FROM ledger
               WHERE version_chain_head = ?
               ORDER BY COALESCE(recorded_at, created_at) ASC""",
            (chain_head,),
        ).fetchall()

        return [dict(r) for r in rows]

    def get_current_version(
        self,
        conn: sqlite3.Connection,
        chain_head: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the latest non-superseded version in a chain."""
        row = conn.execute(
            """SELECT * FROM ledger
               WHERE version_chain_head = ? AND superseded_by IS NULL
               LIMIT 1""",
            (chain_head,),
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# RedactionManager
# ─────────────────────────────────────────────────────────────────────────────

class RedactionManager:
    """Governance-audited redaction and unredaction."""

    def redact(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        reason: str,
        performed_by: str = "system",
    ) -> bool:
        """Redact a memory. Preserves chain pointers. Inserts audit record."""
        now = utc_now_iso()

        cursor = conn.execute(
            "UPDATE ledger SET redacted = 1, updated_at = ? WHERE id = ? AND redacted = 0",
            (now, memory_id),
        )
        if cursor.rowcount == 0:
            return False

        audit_id = f"redact_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO redaction_audit
               (redaction_id, memory_id, action, reason, performed_at, performed_by)
               VALUES (?, ?, 'REDACT', ?, ?, ?)""",
            (audit_id, memory_id, reason, now, performed_by),
        )
        return True

    def unredact(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
        performed_by: str = "system",
    ) -> bool:
        """Unredact a memory. Admin operation, also audited."""
        now = utc_now_iso()

        cursor = conn.execute(
            "UPDATE ledger SET redacted = 0, updated_at = ? WHERE id = ? AND redacted = 1",
            (now, memory_id),
        )
        if cursor.rowcount == 0:
            return False

        audit_id = f"redact_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """INSERT INTO redaction_audit
               (redaction_id, memory_id, action, reason, performed_at, performed_by)
               VALUES (?, ?, 'UNREDACT', 'admin_unredact', ?, ?)""",
            (audit_id, memory_id, now, performed_by),
        )
        return True

    def get_audit_trail(
        self,
        conn: sqlite3.Connection,
        memory_id: str,
    ) -> List[Dict[str, Any]]:
        """Get redaction audit trail for a memory."""
        rows = conn.execute(
            """SELECT redaction_id, memory_id, action, reason, performed_at, performed_by, metadata
               FROM redaction_audit
               WHERE memory_id = ?
               ORDER BY performed_at ASC""",
            (memory_id,),
        ).fetchall()
        return [dict(r) for r in rows]
