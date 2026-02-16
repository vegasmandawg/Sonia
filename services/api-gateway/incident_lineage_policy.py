"""Incident Lineage Policy — v4.2 E2.

Enforces completeness of incident records and continuity of
correlation chains across recovery operations.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

SCHEMA_VERSION = "1.0.0"

# Required fields for a complete incident record
REQUIRED_INCIDENT_FIELDS = frozenset({
    "incident_id",
    "correlation_id",
    "timestamp",
    "severity",
    "failure_class",
    "affected_service",
    "description",
    "resolution_status",
})


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResolutionStatus(Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class IncidentRecord:
    """An immutable incident record with required fields."""
    incident_id: str
    correlation_id: str
    timestamp: str
    severity: Severity
    failure_class: str
    affected_service: str
    description: str
    resolution_status: ResolutionStatus
    parent_correlation_id: str = ""  # empty for root incidents

    def __post_init__(self):
        if not self.incident_id:
            raise ValueError("incident_id must be non-empty")
        if not self.correlation_id:
            raise ValueError("correlation_id must be non-empty")
        if not self.timestamp:
            raise ValueError("timestamp must be non-empty")
        if not self.failure_class:
            raise ValueError("failure_class must be non-empty")
        if not self.affected_service:
            raise ValueError("affected_service must be non-empty")
        if not self.description:
            raise ValueError("description must be non-empty")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "incident_id": self.incident_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "failure_class": self.failure_class,
            "affected_service": self.affected_service,
            "description": self.description,
            "resolution_status": self.resolution_status.value,
            "parent_correlation_id": self.parent_correlation_id,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def has_all_required_fields(self) -> bool:
        """Check that all required fields are present and non-empty."""
        vals = {
            "incident_id": self.incident_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "failure_class": self.failure_class,
            "affected_service": self.affected_service,
            "description": self.description,
            "resolution_status": self.resolution_status.value,
        }
        return all(bool(v) for v in vals.values())


class IncidentLineagePolicy:
    """Enforces incident lineage completeness and correlation continuity."""

    def __init__(self):
        self._incidents: Dict[str, IncidentRecord] = {}
        self._by_correlation: Dict[str, List[str]] = {}  # correlation_id -> [incident_ids]
        self._children: Dict[str, List[str]] = {}  # parent_correlation -> [child_correlations]

    def register(self, record: IncidentRecord) -> None:
        """Register an incident record."""
        if record.incident_id in self._incidents:
            raise ValueError(f"Duplicate incident_id: {record.incident_id}")
        self._incidents[record.incident_id] = record

        if record.correlation_id not in self._by_correlation:
            self._by_correlation[record.correlation_id] = []
        self._by_correlation[record.correlation_id].append(record.incident_id)

        if record.parent_correlation_id:
            if record.parent_correlation_id not in self._children:
                self._children[record.parent_correlation_id] = []
            self._children[record.parent_correlation_id].append(record.correlation_id)

    def check_completeness(self, incident_id: str) -> dict:
        """Check if an incident record has all required fields."""
        record = self._incidents.get(incident_id)
        if not record:
            return {"complete": False, "reason": "incident_not_found"}
        complete = record.has_all_required_fields()
        return {"complete": complete, "incident_id": incident_id}

    def check_correlation_continuity(self, correlation_id: str) -> dict:
        """Check if a correlation chain is continuous (no orphans).

        A chain is continuous if:
        1. The root correlation has at least one incident
        2. All child correlations reference an existing parent
        """
        if correlation_id not in self._by_correlation:
            return {
                "continuous": False,
                "reason": "correlation_not_found",
                "correlation_id": correlation_id,
            }

        # Check all incidents in this correlation have valid parent links
        incident_ids = self._by_correlation[correlation_id]
        broken_links = []
        for iid in incident_ids:
            record = self._incidents[iid]
            if record.parent_correlation_id:
                if record.parent_correlation_id not in self._by_correlation:
                    broken_links.append({
                        "incident_id": iid,
                        "missing_parent": record.parent_correlation_id,
                    })

        return {
            "continuous": len(broken_links) == 0,
            "correlation_id": correlation_id,
            "incident_count": len(incident_ids),
            "broken_links": broken_links,
        }

    def check_chain_completeness(self, root_correlation_id: str) -> dict:
        """Walk from root correlation and verify all descendants are complete."""
        visited: Set[str] = set()
        incomplete: List[str] = []

        def walk(cid: str):
            if cid in visited:
                return
            visited.add(cid)
            for iid in self._by_correlation.get(cid, []):
                if not self._incidents[iid].has_all_required_fields():
                    incomplete.append(iid)
            for child_cid in self._children.get(cid, []):
                walk(child_cid)

        walk(root_correlation_id)
        return {
            "all_complete": len(incomplete) == 0,
            "visited_correlations": len(visited),
            "incomplete_incidents": incomplete,
        }

    def get_lineage(self, correlation_id: str) -> List[IncidentRecord]:
        """Get all incidents in a correlation lineage."""
        ids = self._by_correlation.get(correlation_id, [])
        return [self._incidents[iid] for iid in ids]

    @property
    def incident_count(self) -> int:
        return len(self._incidents)

    @property
    def correlation_count(self) -> int:
        return len(self._by_correlation)
