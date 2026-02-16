"""
Configuration Audit & Drift Detection (Section D: Config Management)
=====================================================================
Schema validation + config drift checks for deterministic config management.
"""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Set


@dataclass
class ConfigFileRecord:
    path: str
    schema_version: str
    sha256: str
    required_keys: List[str] = field(default_factory=list)


class ConfigAuditEngine:
    """Tracks config files, detects drift, validates schemas."""

    def __init__(self):
        self._records: Dict[str, ConfigFileRecord] = {}

    def register(self, path: str, schema_version: str, content: str,
                 required_keys: Optional[List[str]] = None) -> ConfigFileRecord:
        sha = hashlib.sha256(content.encode()).hexdigest()
        record = ConfigFileRecord(
            path=path, schema_version=schema_version, sha256=sha,
            required_keys=required_keys or [],
        )
        self._records[path] = record
        return record

    def check_drift(self, path: str, current_content: str) -> Dict[str, Any]:
        """Check if config has drifted from registered baseline."""
        record = self._records.get(path)
        if record is None:
            return {"status": "UNREGISTERED", "path": path, "drifted": None}
        current_sha = hashlib.sha256(current_content.encode()).hexdigest()
        drifted = current_sha != record.sha256
        return {
            "status": "DRIFTED" if drifted else "CLEAN",
            "path": path,
            "drifted": drifted,
            "baseline_sha256": record.sha256,
            "current_sha256": current_sha,
        }

    def validate_required_keys(self, path: str, config_dict: Dict) -> Dict[str, Any]:
        """Validate that config contains all required keys."""
        record = self._records.get(path)
        if record is None:
            return {"valid": False, "reason": "unregistered", "missing": []}
        missing = [k for k in record.required_keys if k not in config_dict]
        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "present": [k for k in record.required_keys if k in config_dict],
        }

    def list_registered(self) -> List[Dict[str, Any]]:
        return [
            {"path": r.path, "schema_version": r.schema_version, "sha256": r.sha256}
            for r in self._records.values()
        ]

    def check_all_drift(self, content_map: Dict[str, str]) -> Dict[str, Any]:
        """Check drift for all registered configs."""
        results = {}
        for path in self._records:
            if path in content_map:
                results[path] = self.check_drift(path, content_map[path])
            else:
                results[path] = {"status": "MISSING", "path": path, "drifted": None}
        drifted = sum(1 for r in results.values() if r.get("drifted"))
        return {
            "total": len(results),
            "clean": sum(1 for r in results.values() if r.get("status") == "CLEAN"),
            "drifted": drifted,
            "missing": sum(1 for r in results.values() if r.get("status") == "MISSING"),
            "details": results,
        }
