"""
Data schema validation for memory entries.

Validates memory entry structure with:
- Entry type validation (raw, summary, vision_observation, tool_event, etc.)
- Field completeness checks
- Provenance field requirements
- Timestamp format validation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MemoryEntryType(Enum):
    RAW = "raw"
    SUMMARY = "summary"
    VISION_OBSERVATION = "vision_observation"
    TOOL_EVENT = "tool_event"
    CONFIRMATION_EVENT = "confirmation_event"
    SYSTEM_STATE = "system_state"
    FACT = "fact"


# Required fields per entry type
ENTRY_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "raw": {
        "required": ["content", "timestamp", "session_id"],
        "optional": ["user_id", "persona_id", "correlation_id", "provenance"],
    },
    "summary": {
        "required": ["content", "timestamp", "source_entry_ids"],
        "optional": ["session_id", "persona_id", "provenance"],
    },
    "vision_observation": {
        "required": ["content", "timestamp", "frame_index"],
        "optional": ["session_id", "confidence", "provenance"],
    },
    "tool_event": {
        "required": ["content", "timestamp", "tool_name", "action"],
        "optional": ["session_id", "correlation_id", "result", "provenance"],
    },
    "confirmation_event": {
        "required": ["content", "timestamp", "confirmation_id", "status"],
        "optional": ["session_id", "tool_name", "provenance"],
    },
    "system_state": {
        "required": ["content", "timestamp", "state_key"],
        "optional": ["previous_value", "provenance"],
    },
    "fact": {
        "required": ["content", "timestamp", "confidence"],
        "optional": ["source", "provenance", "expires_at"],
    },
}

# Provenance required fields
PROVENANCE_FIELDS = ["source_module", "created_at", "entry_type"]


@dataclass
class SchemaViolation:
    field: str
    message: str
    entry_type: Optional[str] = None
    severity: str = "error"


@dataclass
class EntryValidationResult:
    valid: bool
    entry_type: Optional[str] = None
    violations: List[SchemaViolation] = field(default_factory=list)
    fields_present: List[str] = field(default_factory=list)
    fields_missing: List[str] = field(default_factory=list)
    provenance_valid: bool = False

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "entry_type": self.entry_type,
            "violations": [{"field": v.field, "message": v.message, "severity": v.severity}
                          for v in self.violations],
            "fields_present": self.fields_present,
            "fields_missing": self.fields_missing,
            "provenance_valid": self.provenance_valid,
        }


class DataSchemaValidator:
    """Validates memory entries against the canonical data schema."""

    def __init__(self, schemas: Optional[Dict[str, Dict[str, Any]]] = None):
        self.schemas = schemas or ENTRY_SCHEMAS

    def validate_entry(self, entry: Dict[str, Any]) -> EntryValidationResult:
        """Validate a single memory entry."""
        violations: List[SchemaViolation] = []

        # Check entry_type exists
        entry_type = entry.get("entry_type")
        if not entry_type:
            violations.append(SchemaViolation(
                field="entry_type",
                message="Missing required field 'entry_type'",
            ))
            return EntryValidationResult(
                valid=False,
                violations=violations,
            )

        # Check entry_type is known
        if entry_type not in self.schemas:
            violations.append(SchemaViolation(
                field="entry_type",
                message=f"Unknown entry_type '{entry_type}'. Valid types: {list(self.schemas.keys())}",
                entry_type=entry_type,
            ))
            return EntryValidationResult(
                valid=False,
                entry_type=entry_type,
                violations=violations,
            )

        schema = self.schemas[entry_type]
        required = schema["required"]
        optional = schema.get("optional", [])

        # Check required fields
        fields_present = []
        fields_missing = []
        for f in required:
            if f in entry:
                fields_present.append(f)
            else:
                fields_missing.append(f)
                violations.append(SchemaViolation(
                    field=f,
                    message=f"Required field '{f}' missing for entry_type '{entry_type}'",
                    entry_type=entry_type,
                ))

        # Check content is non-empty string
        if "content" in entry:
            if not isinstance(entry["content"], str):
                violations.append(SchemaViolation(
                    field="content",
                    message=f"'content' must be string, got {type(entry['content']).__name__}",
                    entry_type=entry_type,
                ))
            elif len(entry["content"].strip()) == 0:
                violations.append(SchemaViolation(
                    field="content",
                    message="'content' must not be empty",
                    entry_type=entry_type,
                ))

        # Check timestamp format (basic ISO check)
        if "timestamp" in entry:
            ts = entry["timestamp"]
            if not isinstance(ts, str) or len(ts) < 10:
                violations.append(SchemaViolation(
                    field="timestamp",
                    message="'timestamp' must be ISO 8601 string",
                    entry_type=entry_type,
                ))

        # Check provenance
        provenance_valid = False
        provenance = entry.get("provenance")
        if provenance and isinstance(provenance, dict):
            prov_missing = [f for f in PROVENANCE_FIELDS if f not in provenance]
            if prov_missing:
                violations.append(SchemaViolation(
                    field="provenance",
                    message=f"Provenance missing fields: {prov_missing}",
                    entry_type=entry_type,
                    severity="warning",
                ))
            else:
                provenance_valid = True

        return EntryValidationResult(
            valid=len([v for v in violations if v.severity == "error"]) == 0,
            entry_type=entry_type,
            violations=violations,
            fields_present=fields_present,
            fields_missing=fields_missing,
            provenance_valid=provenance_valid,
        )

    def get_supported_types(self) -> List[str]:
        """Return list of supported entry types."""
        return list(self.schemas.keys())

    def get_required_fields(self, entry_type: str) -> List[str]:
        """Return required fields for a given entry type."""
        if entry_type not in self.schemas:
            return []
        return self.schemas[entry_type]["required"]

    def get_schema_summary(self) -> dict:
        """Return schema summary for audit."""
        return {
            "total_types": len(self.schemas),
            "types": {k: {"required": v["required"], "optional": v.get("optional", [])}
                     for k, v in self.schemas.items()},
            "provenance_fields": PROVENANCE_FIELDS,
        }
