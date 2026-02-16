"""
Incident lineage: correlation chain and required lineage fields.

Provides deterministic tracking of incident propagation through
correlation IDs, with mandatory field validation and chain continuity.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set


REQUIRED_LINEAGE_FIELDS: FrozenSet[str] = frozenset([
    "incident_id",
    "correlation_id",
    "timestamp",
    "source_service",
    "failure_class",
    "severity",
])

OPTIONAL_LINEAGE_FIELDS: FrozenSet[str] = frozenset([
    "parent_incident_id",
    "action_id",
    "adapter_type",
    "retry_count",
    "resolution",
    "dlq_entry_id",
])


@dataclass(frozen=True)
class IncidentNode:
    """A single node in the incident lineage chain."""
    incident_id: str
    correlation_id: str
    timestamp: str
    source_service: str
    failure_class: str
    severity: str  # "critical", "warning", "info"
    parent_incident_id: Optional[str] = None
    action_id: Optional[str] = None
    adapter_type: Optional[str] = None
    retry_count: int = 0
    resolution: Optional[str] = None
    dlq_entry_id: Optional[str] = None

    def has_required_fields(self) -> bool:
        return all([
            self.incident_id,
            self.correlation_id,
            self.timestamp,
            self.source_service,
            self.failure_class,
            self.severity,
        ])

    def fingerprint(self) -> str:
        canonical = (
            f"{self.incident_id}|{self.correlation_id}|{self.timestamp}|"
            f"{self.source_service}|{self.failure_class}|{self.severity}"
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class IncidentLineageChain:
    """Tracks incident propagation with correlation continuity."""

    def __init__(self):
        self._nodes: Dict[str, IncidentNode] = {}
        self._children: Dict[str, List[str]] = {}  # parent_id -> [child_ids]

    def add_node(self, node: IncidentNode) -> None:
        if node.incident_id in self._nodes:
            raise ValueError(f"Duplicate incident_id: {node.incident_id}")
        self._nodes[node.incident_id] = node
        if node.parent_incident_id:
            self._children.setdefault(node.parent_incident_id, []).append(
                node.incident_id
            )

    def get_node(self, incident_id: str) -> Optional[IncidentNode]:
        return self._nodes.get(incident_id)

    def get_chain(self, incident_id: str) -> List[IncidentNode]:
        """Get the full ancestor chain for an incident (root first)."""
        chain = []
        current_id: Optional[str] = incident_id
        visited: Set[str] = set()
        while current_id and current_id in self._nodes and current_id not in visited:
            visited.add(current_id)
            chain.append(self._nodes[current_id])
            current_id = self._nodes[current_id].parent_incident_id
        return list(reversed(chain))

    def get_children(self, incident_id: str) -> List[IncidentNode]:
        child_ids = self._children.get(incident_id, [])
        return sorted(
            [self._nodes[cid] for cid in child_ids if cid in self._nodes],
            key=lambda n: n.incident_id,
        )

    def root_nodes(self) -> List[IncidentNode]:
        return sorted(
            [n for n in self._nodes.values() if n.parent_incident_id is None],
            key=lambda n: n.incident_id,
        )

    def all_nodes(self) -> List[IncidentNode]:
        return sorted(self._nodes.values(), key=lambda n: n.incident_id)

    # -- Validation --

    def check_required_fields(self) -> List[str]:
        """Return incident_ids with missing required fields."""
        return sorted(
            n.incident_id for n in self._nodes.values()
            if not n.has_required_fields()
        )

    def check_correlation_continuity(self) -> List[str]:
        """Return incident_ids where correlation_id differs from parent."""
        broken = []
        for node in self._nodes.values():
            if node.parent_incident_id and node.parent_incident_id in self._nodes:
                parent = self._nodes[node.parent_incident_id]
                if node.correlation_id != parent.correlation_id:
                    broken.append(node.incident_id)
        return sorted(broken)

    def check_dangling_parents(self) -> List[str]:
        """Return incident_ids referencing non-existent parents."""
        return sorted(
            n.incident_id for n in self._nodes.values()
            if n.parent_incident_id and n.parent_incident_id not in self._nodes
        )

    def full_audit(self) -> dict:
        missing_fields = self.check_required_fields()
        broken_correlation = self.check_correlation_continuity()
        dangling_parents = self.check_dangling_parents()
        overall_pass = (
            len(missing_fields) == 0
            and len(broken_correlation) == 0
            and len(dangling_parents) == 0
        )
        return {
            "total_nodes": len(self._nodes),
            "root_count": len(self.root_nodes()),
            "missing_required_fields": missing_fields,
            "broken_correlation_continuity": broken_correlation,
            "dangling_parent_references": dangling_parents,
            "overall_pass": overall_pass,
        }
