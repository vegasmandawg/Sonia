"""
Tests for coverage completeness module.
10+ tests covering section mapping, completeness analysis,
gap detection, and artifact emission.
"""
import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\api-gateway")

from coverage_completeness import (
    CoverageCompletenessAnalyzer,
    SectionMapping,
    SECTION_NAMES,
    GATE_SECTION_MAP,
    TEST_SECTION_MAP,
    ARTIFACT_SECTION_MAP,
)


class TestSectionMapping:
    def test_complete_mapping(self):
        m = SectionMapping(
            "A", "Test",
            gates=["gate1"],
            test_families=["test1"],
            artifact_patterns=["art-*.json"],
        )
        assert m.is_complete
        assert m.missing_fields == []

    def test_incomplete_no_gates(self):
        m = SectionMapping("A", "Test", test_families=["t"], artifact_patterns=["a"])
        assert not m.is_complete
        assert "gates" in m.missing_fields

    def test_incomplete_no_tests(self):
        m = SectionMapping("A", "Test", gates=["g"], artifact_patterns=["a"])
        assert not m.is_complete
        assert "test_families" in m.missing_fields

    def test_incomplete_no_artifacts(self):
        m = SectionMapping("A", "Test", gates=["g"], test_families=["t"])
        assert not m.is_complete
        assert "artifact_patterns" in m.missing_fields

    def test_to_dict(self):
        m = SectionMapping("A", "Test", gates=["g1"])
        d = m.to_dict()
        assert d["section_id"] == "A"
        assert "is_complete" in d
        assert "missing_fields" in d


class TestSectionRegistry:
    def test_all_25_sections_present(self):
        expected = set("ABCDEFGHIJKLMNOPQRSTUVWXY")
        assert set(SECTION_NAMES.keys()) == expected

    def test_gate_map_entries_reference_valid_sections(self):
        valid = set(SECTION_NAMES.keys())
        for gate, sections in GATE_SECTION_MAP.items():
            for s in sections:
                assert s in valid, f"Gate {gate} references invalid section {s}"

    def test_test_map_entries_reference_valid_sections(self):
        valid = set(SECTION_NAMES.keys())
        for test, sections in TEST_SECTION_MAP.items():
            for s in sections:
                assert s in valid, f"Test {test} references invalid section {s}"


class TestCoverageAnalyzer:
    def test_build_section_mappings_all_25(self):
        a = CoverageCompletenessAnalyzer()
        mappings = a.build_section_mappings()
        assert len(mappings) == 25

    def test_full_completeness_result_structure(self):
        a = CoverageCompletenessAnalyzer()
        r = a.check_completeness()
        assert "total_sections" in r
        assert "completeness_pct" in r
        assert "complete_sections" in r
        assert "incomplete_sections" in r

    def test_target_sections_check(self):
        a = CoverageCompletenessAnalyzer()
        r = a.check_target_sections(["J", "S"])
        assert r["total_sections"] == 2
        assert "all_targets_complete" in r

    def test_custom_gate_map(self):
        custom_gates = {"my-gate.py": ["A"]}
        custom_tests = {"test_x": ["A"]}
        custom_arts = {"x-*.json": ["A"]}
        a = CoverageCompletenessAnalyzer(custom_gates, custom_tests, custom_arts)
        r = a.check_target_sections(["A"])
        assert r["all_targets_complete"]

    def test_empty_maps_all_incomplete(self):
        a = CoverageCompletenessAnalyzer({}, {}, {})
        r = a.check_completeness()
        assert r["completeness_pct"] == 0.0
        assert r["incomplete"] == 25

    def test_emit_artifact(self):
        a = CoverageCompletenessAnalyzer()
        with tempfile.TemporaryDirectory() as td:
            path = a.emit_artifact(td, ["J", "M"])
            p = Path(path)
            assert p.exists()
            data = json.loads(p.read_text())
            assert data["total_sections"] == 2

    def test_epic1_targets_complete(self):
        """Critical: all Epic 1 target sections must be fully mapped."""
        a = CoverageCompletenessAnalyzer()
        r = a.check_target_sections(["J", "S", "M", "O", "Q", "W"])
        assert r["all_targets_complete"], (
            f"Incomplete sections: {r['incomplete_sections']} "
            f"missing: {r['missing_details']}"
        )
