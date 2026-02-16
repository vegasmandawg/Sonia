"""
Provenance Registry: Control registry with uniqueness enforcement.
==================================================================
Tracks governance controls with unique IDs, descriptions, and metadata.
Deterministic and pure -- no randomness, no side effects.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass(frozen=True)
class GovernanceControl:
    """A single governance control with provenance metadata."""
    control_id: str
    name: str
    description: str
    category: str  # e.g., "security", "reliability", "observability"
    severity: str  # "critical", "high", "medium", "low"
    source_version: str  # version that introduced this control
    tags: tuple = ()  # immutable tags for classification

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of the control."""
        content = f"{self.control_id}|{self.name}|{self.category}|{self.severity}|{self.source_version}"
        return hashlib.sha256(content.encode()).hexdigest()


class DuplicateControlError(Exception):
    """Raised when a control ID is registered more than once."""
    def __init__(self, control_id: str):
        self.control_id = control_id
        super().__init__(f"Duplicate control ID: {control_id}")


class ControlNotFoundError(Exception):
    """Raised when a control ID is not found in the registry."""
    def __init__(self, control_id: str):
        self.control_id = control_id
        super().__init__(f"Control not found: {control_id}")


class ProvenanceRegistry:
    """
    Registry of governance controls with uniqueness enforcement.

    All operations are deterministic: same inputs produce same outputs.
    """

    def __init__(self):
        self._controls: Dict[str, GovernanceControl] = {}
        self._categories: Dict[str, Set[str]] = {}  # category -> set of control_ids

    def register(self, control: GovernanceControl) -> None:
        """Register a control. Raises DuplicateControlError if ID exists."""
        if control.control_id in self._controls:
            raise DuplicateControlError(control.control_id)
        self._controls[control.control_id] = control
        cat_set = self._categories.setdefault(control.category, set())
        cat_set.add(control.control_id)

    def get(self, control_id: str) -> GovernanceControl:
        """Retrieve a control by ID. Raises ControlNotFoundError if missing."""
        if control_id not in self._controls:
            raise ControlNotFoundError(control_id)
        return self._controls[control_id]

    def list_all(self) -> List[GovernanceControl]:
        """Return all controls sorted by ID (deterministic order)."""
        return [self._controls[k] for k in sorted(self._controls.keys())]

    def list_by_category(self, category: str) -> List[GovernanceControl]:
        """Return controls in a category, sorted by ID."""
        ids = self._categories.get(category, set())
        return [self._controls[cid] for cid in sorted(ids)]

    def list_by_severity(self, severity: str) -> List[GovernanceControl]:
        """Return controls of given severity, sorted by ID."""
        return [c for c in self.list_all() if c.severity == severity]

    def count(self) -> int:
        """Total number of registered controls."""
        return len(self._controls)

    def categories(self) -> List[str]:
        """All categories in sorted order."""
        return sorted(self._categories.keys())

    def has(self, control_id: str) -> bool:
        """Check if a control ID is registered."""
        return control_id in self._controls

    def all_ids(self) -> List[str]:
        """All control IDs in sorted order."""
        return sorted(self._controls.keys())

    def check_uniqueness(self) -> List[str]:
        """
        Verify all control IDs are unique.
        Returns list of duplicate IDs (empty if clean).
        By construction this is always empty, but external callers
        can use this for audit evidence.
        """
        # Since dict keys are unique, this is always empty.
        # But we validate fingerprints for content uniqueness.
        fingerprints: Dict[str, str] = {}
        duplicates = []
        for cid, control in sorted(self._controls.items()):
            fp = control.fingerprint()
            if fp in fingerprints:
                duplicates.append(f"{cid} (same fingerprint as {fingerprints[fp]})")
            else:
                fingerprints[fp] = cid
        return duplicates

    def export_manifest(self) -> Dict:
        """
        Export a deterministic manifest of all controls.
        Same registry state always produces identical output.
        """
        controls_list = []
        for control in self.list_all():
            controls_list.append({
                "control_id": control.control_id,
                "name": control.name,
                "category": control.category,
                "severity": control.severity,
                "source_version": control.source_version,
                "fingerprint": control.fingerprint(),
            })

        # Compute manifest hash over sorted controls
        content = "|".join(c["fingerprint"] for c in controls_list)
        manifest_hash = hashlib.sha256(content.encode()).hexdigest()

        return {
            "control_count": len(controls_list),
            "controls": controls_list,
            "manifest_hash": manifest_hash,
        }
