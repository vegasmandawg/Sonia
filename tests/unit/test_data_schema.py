"""
Unit tests for data_schema.py — DataSchemaValidator.

Covers:
- Valid entries for all 7 types
- Missing entry_type
- Unknown entry_type
- Missing required fields
- Content validation (non-empty, type check)
- Timestamp validation
- Provenance validation (complete + incomplete)
- Schema summary
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"S:\services\api-gateway")

from data_schema import (
    DataSchemaValidator,
    EntryValidationResult,
    ENTRY_SCHEMAS,
    PROVENANCE_FIELDS,
    MemoryEntryType,
)


def _valid_raw() -> dict:
    return {
        "entry_type": "raw",
        "content": "Hello world",
        "timestamp": "2026-02-15T12:00:00Z",
        "session_id": "sess_001",
    }


def _full_provenance() -> dict:
    return {
        "source_module": "api-gateway",
        "created_at": "2026-02-15T12:00:00Z",
        "entry_type": "raw",
    }


class TestDataSchemaValidator:
    """Tests for DataSchemaValidator."""

    def test_valid_raw_entry(self):
        v = DataSchemaValidator()
        result = v.validate_entry(_valid_raw())
        assert result.valid is True
        assert result.entry_type == "raw"

    def test_valid_summary_entry(self):
        v = DataSchemaValidator()
        entry = {
            "entry_type": "summary",
            "content": "Summary text",
            "timestamp": "2026-02-15T12:00:00Z",
            "source_entry_ids": ["e1", "e2"],
        }
        result = v.validate_entry(entry)
        assert result.valid is True

    def test_valid_fact_entry(self):
        v = DataSchemaValidator()
        entry = {
            "entry_type": "fact",
            "content": "User prefers dark mode",
            "timestamp": "2026-02-15T12:00:00Z",
            "confidence": 0.95,
        }
        result = v.validate_entry(entry)
        assert result.valid is True

    def test_missing_entry_type(self):
        v = DataSchemaValidator()
        result = v.validate_entry({"content": "no type"})
        assert result.valid is False
        assert any(viol.field == "entry_type" for viol in result.violations)

    def test_unknown_entry_type(self):
        v = DataSchemaValidator()
        result = v.validate_entry({"entry_type": "alien_type"})
        assert result.valid is False
        assert any("unknown" in viol.message.lower() for viol in result.violations)

    def test_missing_required_field(self):
        v = DataSchemaValidator()
        entry = {"entry_type": "raw", "content": "text"}
        # missing timestamp and session_id
        result = v.validate_entry(entry)
        assert result.valid is False
        assert "timestamp" in result.fields_missing

    def test_empty_content_rejected(self):
        v = DataSchemaValidator()
        entry = _valid_raw()
        entry["content"] = "   "
        result = v.validate_entry(entry)
        assert result.valid is False
        assert any("empty" in viol.message.lower() for viol in result.violations)

    def test_content_wrong_type(self):
        v = DataSchemaValidator()
        entry = _valid_raw()
        entry["content"] = 12345
        result = v.validate_entry(entry)
        assert result.valid is False
        assert any("string" in viol.message.lower() for viol in result.violations)

    def test_timestamp_too_short(self):
        v = DataSchemaValidator()
        entry = _valid_raw()
        entry["timestamp"] = "2026"
        result = v.validate_entry(entry)
        assert any("iso" in viol.message.lower() for viol in result.violations)

    def test_timestamp_wrong_type(self):
        v = DataSchemaValidator()
        entry = _valid_raw()
        entry["timestamp"] = 1234567890
        result = v.validate_entry(entry)
        assert any("iso" in viol.message.lower() for viol in result.violations)

    def test_provenance_valid(self):
        v = DataSchemaValidator()
        entry = _valid_raw()
        entry["provenance"] = _full_provenance()
        result = v.validate_entry(entry)
        assert result.valid is True
        assert result.provenance_valid is True

    def test_provenance_incomplete(self):
        v = DataSchemaValidator()
        entry = _valid_raw()
        entry["provenance"] = {"source_module": "api-gateway"}  # missing created_at, entry_type
        result = v.validate_entry(entry)
        # incomplete provenance is a warning, not error
        assert result.valid is True
        assert result.provenance_valid is False

    def test_all_seven_types_supported(self):
        v = DataSchemaValidator()
        types = v.get_supported_types()
        assert len(types) == 7
        for t in MemoryEntryType:
            assert t.value in types

    def test_get_required_fields(self):
        v = DataSchemaValidator()
        required = v.get_required_fields("raw")
        assert "content" in required
        assert "timestamp" in required
        assert "session_id" in required

    def test_get_required_fields_unknown_type(self):
        v = DataSchemaValidator()
        assert v.get_required_fields("nonexistent") == []

    def test_schema_summary(self):
        v = DataSchemaValidator()
        summary = v.get_schema_summary()
        assert summary["total_types"] == 7
        assert "provenance_fields" in summary
        assert summary["provenance_fields"] == PROVENANCE_FIELDS

    def test_to_dict(self):
        v = DataSchemaValidator()
        result = v.validate_entry(_valid_raw())
        d = result.to_dict()
        assert "valid" in d
        assert "violations" in d
        assert "provenance_valid" in d

    def test_tool_event_entry(self):
        v = DataSchemaValidator()
        entry = {
            "entry_type": "tool_event",
            "content": "Ran file.read",
            "timestamp": "2026-02-15T12:00:00Z",
            "tool_name": "file.read",
            "action": "execute",
        }
        result = v.validate_entry(entry)
        assert result.valid is True
