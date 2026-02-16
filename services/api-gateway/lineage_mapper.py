"""
Lineage Mapper: Control-to-gate-to-test-to-artifact mapping.
==============================================================
Maps governance controls through the full verification chain:
  control -> gate check -> test family -> artifact pattern

Deterministic and pure. All operations produce consistent output
regardless of insertion order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple


@dataclass(frozen=True)
class GateCheckBinding:
    """Binding from a control to a gate check."""
    control_id: str
    gate_file: str
    check_name: str


@dataclass(frozen=True)
class TestFamilyBinding:
    """Binding from a control to a test family."""
    control_id: str
    test_file: str
    test_prefix: str  # e.g., "test_session_" or class name


@dataclass(frozen=True)
class ArtifactPatternBinding:
    """Binding from a control to an artifact naming pattern."""
    control_id: str
    artifact_pattern: str  # glob-like pattern, e.g. "v41-e1-gate-*.json"
    artifact_type: str  # "gate_report", "test_summary", "manifest", "audit_log"


class OrphanGateCheckError(Exception):
    """Gate check has no control mapping."""
    def __init__(self, gate_file: str, check_name: str):
        self.gate_file = gate_file
        self.check_name = check_name
        super().__init__(f"Orphan gate check: {gate_file}::{check_name}")


class OrphanTestFamilyError(Exception):
    """Test family has no control mapping."""
    def __init__(self, test_file: str, test_prefix: str):
        self.test_file = test_file
        self.test_prefix = test_prefix
        super().__init__(f"Orphan test family: {test_file}::{test_prefix}")


class LineageMapper:
    """
    Maps controls to gate checks, test families, and artifact patterns.

    All operations are deterministic: iteration order is always sorted.
    """

    def __init__(self):
        self._gate_bindings: List[GateCheckBinding] = []
        self._test_bindings: List[TestFamilyBinding] = []
        self._artifact_bindings: List[ArtifactPatternBinding] = []
        self._known_control_ids: Set[str] = set()

    def register_control_id(self, control_id: str) -> None:
        """Register a control ID as known (from ProvenanceRegistry)."""
        self._known_control_ids.add(control_id)

    def register_control_ids(self, control_ids: List[str]) -> None:
        """Bulk register control IDs."""
        self._known_control_ids.update(control_ids)

    def bind_gate_check(self, binding: GateCheckBinding) -> None:
        """Add a control-to-gate-check binding."""
        self._gate_bindings.append(binding)

    def bind_test_family(self, binding: TestFamilyBinding) -> None:
        """Add a control-to-test-family binding."""
        self._test_bindings.append(binding)

    def bind_artifact_pattern(self, binding: ArtifactPatternBinding) -> None:
        """Add a control-to-artifact-pattern binding."""
        self._artifact_bindings.append(binding)

    # ---- Query methods ----

    def gates_for_control(self, control_id: str) -> List[GateCheckBinding]:
        """All gate checks mapped to a control, sorted."""
        return sorted(
            [b for b in self._gate_bindings if b.control_id == control_id],
            key=lambda b: (b.gate_file, b.check_name),
        )

    def tests_for_control(self, control_id: str) -> List[TestFamilyBinding]:
        """All test families mapped to a control, sorted."""
        return sorted(
            [b for b in self._test_bindings if b.control_id == control_id],
            key=lambda b: (b.test_file, b.test_prefix),
        )

    def artifacts_for_control(self, control_id: str) -> List[ArtifactPatternBinding]:
        """All artifact patterns mapped to a control, sorted."""
        return sorted(
            [b for b in self._artifact_bindings if b.control_id == control_id],
            key=lambda b: (b.artifact_pattern, b.artifact_type),
        )

    # ---- Coverage checks ----

    def controls_without_gates(self) -> List[str]:
        """Control IDs that have no gate check mappings."""
        mapped = {b.control_id for b in self._gate_bindings}
        return sorted(self._known_control_ids - mapped)

    def controls_without_tests(self) -> List[str]:
        """Control IDs that have no test family mappings."""
        mapped = {b.control_id for b in self._test_bindings}
        return sorted(self._known_control_ids - mapped)

    def controls_without_artifacts(self) -> List[str]:
        """Control IDs that have no artifact pattern mappings."""
        mapped = {b.control_id for b in self._artifact_bindings}
        return sorted(self._known_control_ids - mapped)

    # ---- Orphan detection ----

    def orphan_gate_checks(self) -> List[Tuple[str, str]]:
        """Gate checks that reference unknown control IDs."""
        return sorted(
            [(b.gate_file, b.check_name)
             for b in self._gate_bindings
             if b.control_id not in self._known_control_ids],
            key=lambda x: x,
        )

    def orphan_test_families(self) -> List[Tuple[str, str]]:
        """Test families that reference unknown control IDs."""
        return sorted(
            [(b.test_file, b.test_prefix)
             for b in self._test_bindings
             if b.control_id not in self._known_control_ids],
            key=lambda x: x,
        )

    # ---- Completeness report ----

    def completeness_report(self) -> Dict:
        """
        Generate a deterministic completeness report.
        Returns coverage stats and any gaps.
        """
        total = len(self._known_control_ids)
        no_gates = self.controls_without_gates()
        no_tests = self.controls_without_tests()
        no_artifacts = self.controls_without_artifacts()
        orphan_gates = self.orphan_gate_checks()
        orphan_tests = self.orphan_test_families()

        fully_mapped = sorted(
            self._known_control_ids
            - set(no_gates) - set(no_tests) - set(no_artifacts)
        )

        return {
            "total_controls": total,
            "fully_mapped_count": len(fully_mapped),
            "fully_mapped_ids": fully_mapped,
            "controls_without_gates": no_gates,
            "controls_without_tests": no_tests,
            "controls_without_artifacts": no_artifacts,
            "orphan_gate_checks": orphan_gates,
            "orphan_test_families": orphan_tests,
            "completeness_pct": round(len(fully_mapped) / total * 100, 1) if total > 0 else 0.0,
        }

    def artifact_naming_check(self, required_patterns: List[str]) -> Dict:
        """
        Verify that all required artifact patterns are bound to at least one control.
        Returns pass/fail per pattern.
        """
        bound_patterns = {b.artifact_pattern for b in self._artifact_bindings}
        results = {}
        for pat in sorted(required_patterns):
            results[pat] = pat in bound_patterns
        return results
