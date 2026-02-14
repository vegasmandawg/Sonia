"""Configuration validation against JSON Schema for SONIA v3.0.0+

Validates sonia-config.json against the canonical schema, applies
environment variable overlays, and provides typed access to config sections.

Usage:
    from config_validator import SoniaConfig, ConfigValidationError
    cfg = SoniaConfig()
    model_cfg = cfg.get("model_router")

Environment variable overlays:
    SONIA_MODEL_ROUTER__DEFAULT_MODEL=ollama/qwen2.5:7b
    SONIA_MEMORY_ENGINE__LEDGER_PATH=D:\\data\\memory.db
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import jsonschema

logger = logging.getLogger("sonia.config")

_DEFAULT_CONFIG_PATH = Path(r"S:\config\sonia-config.json")
_DEFAULT_SCHEMA_PATH = Path(r"S:\config\schemas\sonia-config.schema.json")


class ConfigValidationError(Exception):
    """Raised when config fails schema validation."""
    pass


class SoniaConfig:
    """Validated SONIA configuration with environment variable overlay support."""

    def __init__(
        self,
        config_path: Optional[str] = None,
        schema_path: Optional[str] = None,
    ):
        self.config_path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self.schema_path = Path(schema_path) if schema_path else _DEFAULT_SCHEMA_PATH
        self._raw: Dict[str, Any] = {}
        self._validated: Dict[str, Any] = {}
        self._load_and_validate()

    def _load_and_validate(self) -> None:
        """Load config, validate against schema, apply env overlays."""
        # Load raw config
        if not self.config_path.exists():
            raise ConfigValidationError(f"Config file not found: {self.config_path}")
        with open(self.config_path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)

        # Load and validate against schema (if schema exists)
        if self.schema_path.exists():
            with open(self.schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            try:
                jsonschema.validate(instance=self._raw, schema=schema)
            except jsonschema.ValidationError as e:
                path = ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "(root)"
                raise ConfigValidationError(
                    f"Config validation failed at '{path}': {e.message}"
                ) from e
        else:
            logger.warning("Schema file not found at %s, skipping validation", self.schema_path)

        # Apply environment variable overlays
        self._validated = self._apply_env_overlays(json.loads(json.dumps(self._raw)))

    def _apply_env_overlays(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply SONIA_SECTION__KEY environment variables as overrides.

        Format: SONIA_{SECTION}__{KEY}={VALUE}
        Section and key are case-insensitive, matched to existing config keys.
        Type coercion is based on the existing value's type.
        """
        for env_key, env_val in os.environ.items():
            if not env_key.startswith("SONIA_"):
                continue
            rest = env_key[6:]  # strip SONIA_ prefix
            if "__" not in rest:
                continue
            parts = rest.split("__", 1)
            if len(parts) != 2:
                continue
            section, key = parts[0].lower(), parts[1].lower()

            if section not in config:
                continue
            if not isinstance(config[section], dict):
                continue
            if key not in config[section]:
                logger.debug("Env overlay %s: key '%s' not in section '%s', skipping", env_key, key, section)
                continue

            existing = config[section][key]
            try:
                if isinstance(existing, bool):
                    config[section][key] = env_val.lower() in ("1", "true", "yes")
                elif isinstance(existing, int):
                    config[section][key] = int(env_val)
                elif isinstance(existing, float):
                    config[section][key] = float(env_val)
                else:
                    config[section][key] = env_val
                logger.info("Env overlay applied: %s.%s = %r", section, key, config[section][key])
            except (ValueError, TypeError) as e:
                logger.warning("Env overlay %s: type coercion failed: %s", env_key, e)

        return config

    def get(self, section: str) -> Dict[str, Any]:
        """Get a config section dict (post-overlay)."""
        return self._validated.get(section, {})

    def get_service(self, name: str) -> Dict[str, Any]:
        """Get a service definition by key name."""
        return self._validated.get("services", {}).get(name, {})

    @property
    def version(self) -> str:
        return self._validated.get("sonia_version", "unknown")

    @property
    def schema_version(self) -> str:
        return self._validated.get("config_schema", "unknown")

    @property
    def raw(self) -> Dict[str, Any]:
        return self._raw
