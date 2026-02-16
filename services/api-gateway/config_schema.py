"""
Config schema validation for sonia-config.json.

Provides strict versioned schema validation with:
- Required keys enforcement
- Type validation for all config values
- Unknown key rejection
- Schema version tracking
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class SchemaVersion(Enum):
    V1_0 = "1.0"
    V1_1 = "1.1"

    @classmethod
    def latest(cls) -> "SchemaVersion":
        return cls.V1_1


# ---- Schema definitions ----

FIELD_SPECS: Dict[str, Dict[str, Any]] = {
    # Core fields
    "schema_version": {"type": str, "required": True, "description": "Schema version identifier"},
    "project_name": {"type": str, "required": True, "description": "Project name"},
    "environment": {"type": str, "required": False, "description": "Environment (dev/staging/prod)",
                    "allowed_values": ["dev", "staging", "prod"]},
    # Service ports
    "api_gateway_port": {"type": int, "required": True, "description": "API gateway port",
                         "min": 1024, "max": 65535},
    "model_router_port": {"type": int, "required": True, "description": "Model router port",
                          "min": 1024, "max": 65535},
    "memory_engine_port": {"type": int, "required": True, "description": "Memory engine port",
                           "min": 1024, "max": 65535},
    "pipecat_port": {"type": int, "required": False, "description": "Pipecat port",
                     "min": 1024, "max": 65535},
    "openclaw_port": {"type": int, "required": False, "description": "OpenClaw port",
                      "min": 1024, "max": 65535},
    "eva_os_port": {"type": int, "required": False, "description": "EVA-OS port",
                    "min": 1024, "max": 65535},
    # Feature flags
    "dev_mode": {"type": bool, "required": False, "description": "Developer mode flag"},
    "auth_enabled": {"type": bool, "required": False, "description": "Auth enforcement flag"},
    # Limits
    "max_output_chars": {"type": int, "required": False, "description": "Max output characters",
                         "min": 100, "max": 100000},
    "max_concurrent_sessions": {"type": int, "required": False, "description": "Max concurrent sessions",
                                "min": 1, "max": 10000},
    "session_ttl_seconds": {"type": int, "required": False, "description": "Session TTL in seconds",
                            "min": 60, "max": 86400},
}


@dataclass
class ValidationError:
    field: str
    message: str
    severity: str = "error"  # error, warning


@dataclass
class ValidationResult:
    valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    schema_version: Optional[str] = None
    fields_checked: int = 0
    unknown_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": [{"field": e.field, "message": e.message} for e in self.errors],
            "warnings": [{"field": w.field, "message": w.message} for w in self.warnings],
            "schema_version": self.schema_version,
            "fields_checked": self.fields_checked,
            "unknown_keys": self.unknown_keys,
        }


class ConfigSchemaValidator:
    """Validates sonia-config.json against the canonical schema."""

    def __init__(self, schema_specs: Optional[Dict[str, Dict[str, Any]]] = None):
        self.specs = schema_specs or FIELD_SPECS

    def validate(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate a config dict against the schema."""
        errors: List[ValidationError] = []
        warnings: List[ValidationError] = []
        fields_checked = 0

        # Check required fields
        for field_name, spec in self.specs.items():
            if spec.get("required", False) and field_name not in config:
                errors.append(ValidationError(
                    field=field_name,
                    message=f"Required field '{field_name}' is missing",
                ))

        # Check each provided field
        for key, value in config.items():
            if key not in self.specs:
                warnings.append(ValidationError(
                    field=key,
                    message=f"Unknown key '{key}' not in schema",
                    severity="warning",
                ))
                continue

            fields_checked += 1
            spec = self.specs[key]

            # Type check
            expected_type = spec["type"]
            if not isinstance(value, expected_type):
                errors.append(ValidationError(
                    field=key,
                    message=f"Expected type {expected_type.__name__}, got {type(value).__name__}",
                ))
                continue

            # Range check for integers
            if expected_type == int:
                if "min" in spec and value < spec["min"]:
                    errors.append(ValidationError(
                        field=key,
                        message=f"Value {value} below minimum {spec['min']}",
                    ))
                if "max" in spec and value > spec["max"]:
                    errors.append(ValidationError(
                        field=key,
                        message=f"Value {value} above maximum {spec['max']}",
                    ))

            # Allowed values check
            if "allowed_values" in spec and value not in spec["allowed_values"]:
                errors.append(ValidationError(
                    field=key,
                    message=f"Value '{value}' not in allowed values: {spec['allowed_values']}",
                ))

        schema_version = config.get("schema_version")
        unknown_keys = [w.field for w in warnings]

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            schema_version=schema_version,
            fields_checked=fields_checked,
            unknown_keys=unknown_keys,
        )

    def validate_file(self, path: Path) -> ValidationResult:
        """Validate a config file."""
        if not path.exists():
            return ValidationResult(
                valid=False,
                errors=[ValidationError(field="__file__", message=f"File not found: {path}")],
            )
        try:
            with open(path, "r") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            return ValidationResult(
                valid=False,
                errors=[ValidationError(field="__file__", message=f"Invalid JSON: {e}")],
            )
        return self.validate(config)

    def get_schema_summary(self) -> dict:
        """Return schema summary for audit purposes."""
        required = [k for k, v in self.specs.items() if v.get("required")]
        optional = [k for k, v in self.specs.items() if not v.get("required")]
        return {
            "total_fields": len(self.specs),
            "required_fields": len(required),
            "optional_fields": len(optional),
            "required_keys": required,
            "optional_keys": optional,
        }
