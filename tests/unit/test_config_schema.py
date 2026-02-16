"""
Unit tests for config_schema.py — ConfigSchemaValidator.

Covers:
- Required field enforcement
- Type validation
- Range validation (min/max)
- Allowed values validation
- Unknown key rejection
- File validation (valid JSON, missing file, invalid JSON)
- Schema summary
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\api-gateway")

from config_schema import ConfigSchemaValidator, ValidationResult, FIELD_SPECS, SchemaVersion


def _valid_config() -> dict:
    """Return a minimal valid config dict."""
    return {
        "schema_version": "1.1",
        "project_name": "sonia",
        "api_gateway_port": 7000,
        "model_router_port": 7010,
        "memory_engine_port": 7020,
    }


class TestConfigSchemaValidator:
    """Tests for ConfigSchemaValidator."""

    def test_valid_config_passes(self):
        v = ConfigSchemaValidator()
        result = v.validate(_valid_config())
        assert result.valid is True
        assert len(result.errors) == 0

    def test_missing_required_field(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        del cfg["schema_version"]
        result = v.validate(cfg)
        assert result.valid is False
        assert any(e.field == "schema_version" for e in result.errors)

    def test_all_required_fields_missing(self):
        v = ConfigSchemaValidator()
        result = v.validate({})
        assert result.valid is False
        required = [k for k, s in FIELD_SPECS.items() if s.get("required")]
        for r in required:
            assert any(e.field == r for e in result.errors), f"Missing error for {r}"

    def test_type_mismatch_string_for_int(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["api_gateway_port"] = "not_a_number"
        result = v.validate(cfg)
        assert result.valid is False
        assert any(e.field == "api_gateway_port" for e in result.errors)

    def test_type_mismatch_int_for_bool(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["dev_mode"] = 1  # should be bool
        result = v.validate(cfg)
        # int is not bool in Python isinstance check
        assert any(e.field == "dev_mode" for e in result.errors)

    def test_port_below_minimum(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["api_gateway_port"] = 80  # below 1024
        result = v.validate(cfg)
        assert result.valid is False
        assert any("below minimum" in e.message for e in result.errors)

    def test_port_above_maximum(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["api_gateway_port"] = 70000  # above 65535
        result = v.validate(cfg)
        assert result.valid is False
        assert any("above maximum" in e.message for e in result.errors)

    def test_allowed_values_valid(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["environment"] = "prod"
        result = v.validate(cfg)
        assert result.valid is True

    def test_allowed_values_invalid(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["environment"] = "production"  # not in [dev, staging, prod]
        result = v.validate(cfg)
        assert result.valid is False
        assert any(e.field == "environment" for e in result.errors)

    def test_unknown_keys_warned(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["totally_unknown"] = "value"
        result = v.validate(cfg)
        assert result.valid is True  # unknown keys are warnings, not errors
        assert "totally_unknown" in result.unknown_keys

    def test_validate_file_valid(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            f.flush()
            result = v.validate_file(Path(f.name))
        assert result.valid is True

    def test_validate_file_missing(self):
        v = ConfigSchemaValidator()
        result = v.validate_file(Path("/nonexistent/config.json"))
        assert result.valid is False
        assert any("not found" in e.message.lower() for e in result.errors)

    def test_validate_file_invalid_json(self):
        v = ConfigSchemaValidator()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json!!}")
            f.flush()
            result = v.validate_file(Path(f.name))
        assert result.valid is False
        assert any("invalid json" in e.message.lower() for e in result.errors)

    def test_schema_summary(self):
        v = ConfigSchemaValidator()
        summary = v.get_schema_summary()
        assert summary["total_fields"] == len(FIELD_SPECS)
        assert summary["required_fields"] > 0
        assert len(summary["required_keys"]) == summary["required_fields"]

    def test_to_dict(self):
        v = ConfigSchemaValidator()
        result = v.validate(_valid_config())
        d = result.to_dict()
        assert "valid" in d
        assert "errors" in d
        assert "schema_version" in d

    def test_schema_version_latest(self):
        assert SchemaVersion.latest() == SchemaVersion.V1_1

    def test_optional_fields_accepted(self):
        v = ConfigSchemaValidator()
        cfg = _valid_config()
        cfg["dev_mode"] = True
        cfg["auth_enabled"] = False
        cfg["max_output_chars"] = 4000
        cfg["max_concurrent_sessions"] = 100
        cfg["session_ttl_seconds"] = 3600
        result = v.validate(cfg)
        assert result.valid is True
        assert result.fields_checked >= 8
