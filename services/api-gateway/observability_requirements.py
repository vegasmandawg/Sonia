"""
Observability Requirements (Section N: Observability)
======================================================
Required telemetry field completeness and correlation continuity checks.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Set, Optional


# Required telemetry fields for each entry type
REQUIRED_TELEMETRY_FIELDS = {
    "log_entry": ["timestamp", "level", "message", "service", "correlation_id"],
    "metric_point": ["timestamp", "metric_name", "value", "unit", "service"],
    "trace_span": ["trace_id", "span_id", "service", "operation", "start_time", "duration_ms"],
    "health_check": ["timestamp", "service", "status", "latency_ms"],
    "audit_event": ["timestamp", "actor", "action", "resource", "correlation_id"],
}


@dataclass
class TelemetryFieldPolicy:
    entry_type: str
    required_fields: List[str]
    optional_fields: List[str] = field(default_factory=list)


class ObservabilityRequirements:
    """Validates telemetry field completeness and correlation continuity."""

    def __init__(self, custom_requirements: Optional[Dict[str, List[str]]] = None):
        self._requirements = custom_requirements if custom_requirements is not None else REQUIRED_TELEMETRY_FIELDS

    def check_field_completeness(self, entry_type: str, entry: Dict) -> Dict[str, Any]:
        """Check if an entry has all required telemetry fields."""
        required = self._requirements.get(entry_type)
        if required is None:
            return {"valid": False, "reason": f"Unknown entry type: {entry_type}"}
        missing = [f for f in required if f not in entry]
        return {
            "valid": len(missing) == 0,
            "entry_type": entry_type,
            "missing": missing,
            "present": [f for f in required if f in entry],
        }

    def check_correlation_continuity(self, entries: List[Dict]) -> Dict[str, Any]:
        """Check that correlation IDs are consistently present across entries."""
        total = len(entries)
        with_corr = sum(1 for e in entries if "correlation_id" in e)
        without_corr = total - with_corr
        unique_ids: Set[str] = set()
        for e in entries:
            cid = e.get("correlation_id")
            if cid:
                unique_ids.add(cid)
        return {
            "total_entries": total,
            "with_correlation_id": with_corr,
            "without_correlation_id": without_corr,
            "coverage_pct": round(with_corr / total * 100, 1) if total > 0 else 0.0,
            "unique_correlation_ids": len(unique_ids),
            "complete": without_corr == 0,
        }

    def check_all_types(self, samples: Dict[str, Dict]) -> Dict[str, Any]:
        """Check field completeness across all entry types."""
        results = {}
        for entry_type, sample in samples.items():
            results[entry_type] = self.check_field_completeness(entry_type, sample)
        all_valid = all(r["valid"] for r in results.values())
        return {
            "all_valid": all_valid,
            "total_types": len(results),
            "valid_count": sum(1 for r in results.values() if r["valid"]),
            "results": results,
        }

    def list_requirements(self) -> Dict[str, List[str]]:
        return dict(self._requirements)
