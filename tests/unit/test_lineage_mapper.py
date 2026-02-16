"""Tests for lineage_mapper.py — 11 tests."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from lineage_mapper import (
    LineageMapper, GateCheckBinding, TestFamilyBinding, ArtifactPatternBinding,
)


def _setup_mapper():
    m = LineageMapper()
    m.register_control_ids(["CTL-001", "CTL-002", "CTL-003"])
    return m


class TestBindings:
    def test_bind_gate_check(self):
        m = _setup_mapper()
        m.bind_gate_check(GateCheckBinding("CTL-001", "gate.py", "check_auth"))
        gates = m.gates_for_control("CTL-001")
        assert len(gates) == 1
        assert gates[0].check_name == "check_auth"

    def test_bind_test_family(self):
        m = _setup_mapper()
        m.bind_test_family(TestFamilyBinding("CTL-001", "test_auth.py", "TestAuth"))
        tests = m.tests_for_control("CTL-001")
        assert len(tests) == 1

    def test_bind_artifact_pattern(self):
        m = _setup_mapper()
        m.bind_artifact_pattern(ArtifactPatternBinding("CTL-001", "v41-*.json", "gate_report"))
        arts = m.artifacts_for_control("CTL-001")
        assert len(arts) == 1


class TestCoverage:
    def test_controls_without_gates(self):
        m = _setup_mapper()
        m.bind_gate_check(GateCheckBinding("CTL-001", "gate.py", "c1"))
        no_gates = m.controls_without_gates()
        assert "CTL-002" in no_gates
        assert "CTL-003" in no_gates
        assert "CTL-001" not in no_gates

    def test_controls_without_tests(self):
        m = _setup_mapper()
        no_tests = m.controls_without_tests()
        assert len(no_tests) == 3  # none bound yet

    def test_controls_without_artifacts(self):
        m = _setup_mapper()
        m.bind_artifact_pattern(ArtifactPatternBinding("CTL-001", "*.json", "manifest"))
        no_arts = m.controls_without_artifacts()
        assert len(no_arts) == 2


class TestOrphans:
    def test_orphan_gate_check_detected(self):
        m = _setup_mapper()
        m.bind_gate_check(GateCheckBinding("CTL-UNKNOWN", "gate.py", "check_x"))
        orphans = m.orphan_gate_checks()
        assert len(orphans) == 1
        assert orphans[0] == ("gate.py", "check_x")

    def test_orphan_test_family_detected(self):
        m = _setup_mapper()
        m.bind_test_family(TestFamilyBinding("CTL-ORPHAN", "test.py", "TestX"))
        orphans = m.orphan_test_families()
        assert len(orphans) == 1

    def test_no_orphans_when_clean(self):
        m = _setup_mapper()
        m.bind_gate_check(GateCheckBinding("CTL-001", "gate.py", "c1"))
        assert m.orphan_gate_checks() == []


class TestCompleteness:
    def test_full_completeness(self):
        m = _setup_mapper()
        for cid in ["CTL-001", "CTL-002", "CTL-003"]:
            m.bind_gate_check(GateCheckBinding(cid, "gate.py", f"c_{cid}"))
            m.bind_test_family(TestFamilyBinding(cid, "test.py", f"T_{cid}"))
            m.bind_artifact_pattern(ArtifactPatternBinding(cid, f"{cid}-*.json", "gate_report"))
        report = m.completeness_report()
        assert report["completeness_pct"] == 100.0
        assert report["fully_mapped_count"] == 3

    def test_artifact_naming_check(self):
        m = _setup_mapper()
        m.bind_artifact_pattern(ArtifactPatternBinding("CTL-001", "v41-*.json", "gate_report"))
        result = m.artifact_naming_check(["v41-*.json", "missing-*.json"])
        assert result["v41-*.json"] is True
        assert result["missing-*.json"] is False
