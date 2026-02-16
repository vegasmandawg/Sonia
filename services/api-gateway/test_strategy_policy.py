"""
Test Strategy Policy (Section T: Release/Test Strategy)
=========================================================
Enforces test plan completeness and coverage intent mapping.
Ensures every section has declared test coverage and gate evidence.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set


@dataclass
class SectionTestMapping:
    section_id: str
    test_files: List[str] = field(default_factory=list)
    gate_checks: List[str] = field(default_factory=list)
    artifact_patterns: List[str] = field(default_factory=list)
    has_negative_tests: bool = False

    @property
    def is_mapped(self) -> bool:
        return bool(self.test_files) and bool(self.gate_checks) and bool(self.artifact_patterns)


class TestStrategyPolicy:
    """Validates test strategy completeness for scoped sections."""

    def __init__(self):
        self._mappings: Dict[str, SectionTestMapping] = {}

    def declare_section(self, section_id: str, test_files: List[str],
                        gate_checks: List[str], artifact_patterns: List[str],
                        has_negative_tests: bool = False) -> None:
        self._mappings[section_id] = SectionTestMapping(
            section_id=section_id,
            test_files=test_files,
            gate_checks=gate_checks,
            artifact_patterns=artifact_patterns,
            has_negative_tests=has_negative_tests,
        )

    def check_completeness(self, scoped_sections: List[str]) -> Dict[str, Any]:
        """Check that all scoped sections have complete test mappings."""
        results = {}
        unmapped = []
        partial = []
        complete = []
        for sid in scoped_sections:
            m = self._mappings.get(sid)
            if m is None:
                unmapped.append(sid)
                results[sid] = {"status": "UNMAPPED", "missing": ["test_files", "gate_checks", "artifact_patterns"]}
            elif not m.is_mapped:
                partial.append(sid)
                missing = []
                if not m.test_files:
                    missing.append("test_files")
                if not m.gate_checks:
                    missing.append("gate_checks")
                if not m.artifact_patterns:
                    missing.append("artifact_patterns")
                results[sid] = {"status": "PARTIAL", "missing": missing}
            else:
                complete.append(sid)
                results[sid] = {"status": "COMPLETE", "missing": []}
        return {
            "total": len(scoped_sections),
            "complete": len(complete),
            "partial": len(partial),
            "unmapped": len(unmapped),
            "all_complete": len(partial) == 0 and len(unmapped) == 0,
            "details": results,
        }

    def check_negative_test_coverage(self, scoped_sections: List[str]) -> Dict[str, Any]:
        """Check that sections have negative/failure-path test assertions."""
        with_negative = []
        without_negative = []
        for sid in scoped_sections:
            m = self._mappings.get(sid)
            if m and m.has_negative_tests:
                with_negative.append(sid)
            else:
                without_negative.append(sid)
        return {
            "with_negative_tests": with_negative,
            "without_negative_tests": without_negative,
            "coverage_pct": round(len(with_negative) / len(scoped_sections) * 100, 1) if scoped_sections else 0.0,
        }

    def check_duplicates(self, scoped_sections: List[str]) -> Dict[str, Any]:
        """Check for duplicate/conflicting section mappings."""
        seen_tests: Dict[str, List[str]] = {}
        for sid in scoped_sections:
            m = self._mappings.get(sid)
            if m:
                for tf in m.test_files:
                    seen_tests.setdefault(tf, []).append(sid)
        duplicates = {tf: secs for tf, secs in seen_tests.items() if len(secs) > 1}
        return {
            "has_duplicates": bool(duplicates),
            "duplicate_mappings": duplicates,
        }

    def get_strategy_report(self, scoped_sections: List[str]) -> Dict[str, Any]:
        """Consolidated strategy report."""
        completeness = self.check_completeness(scoped_sections)
        negatives = self.check_negative_test_coverage(scoped_sections)
        duplicates = self.check_duplicates(scoped_sections)
        return {
            "completeness": completeness,
            "negative_tests": negatives,
            "duplicates": duplicates,
            "verdict": "PASS" if completeness["all_complete"] else "FAIL",
        }
