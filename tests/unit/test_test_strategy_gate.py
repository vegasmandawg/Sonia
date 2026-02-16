"""
Test Strategy Gate Tests (12+ tests)
=====================================
Tests for section-to-test mapping completeness, gate-to-evidence mapping,
missing/partial mapping failures, and duplicate/conflicting checks.
"""
import sys

sys.path.insert(0, r"S:\services\api-gateway")

from test_strategy_policy import TestStrategyPolicy, SectionTestMapping


class TestSectionMapping:
    def test_fully_mapped_section(self):
        m = SectionTestMapping(
            "A", test_files=["test_a.py"],
            gate_checks=["gate_a.py"],
            artifact_patterns=["a-*.json"],
        )
        assert m.is_mapped

    def test_unmapped_section(self):
        m = SectionTestMapping("A")
        assert not m.is_mapped

    def test_partial_mapping(self):
        m = SectionTestMapping("A", test_files=["test_a.py"])
        assert not m.is_mapped


class TestCompletenessCheck:
    def test_all_complete(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], ["g.py"], ["a-*.json"])
        p.declare_section("D", ["t.py"], ["g.py"], ["a-*.json"])
        r = p.check_completeness(["C", "D"])
        assert r["all_complete"]
        assert r["complete"] == 2

    def test_unmapped_section_detected(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], ["g.py"], ["a-*.json"])
        r = p.check_completeness(["C", "D"])
        assert not r["all_complete"]
        assert r["unmapped"] == 1

    def test_partial_section_detected(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], [], ["a-*.json"])
        r = p.check_completeness(["C"])
        assert not r["all_complete"]
        assert r["partial"] == 1
        assert "gate_checks" in r["details"]["C"]["missing"]

    def test_mixed_status(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], ["g.py"], ["a-*.json"])
        p.declare_section("D", ["t.py"], [], [])
        r = p.check_completeness(["C", "D", "K"])
        assert r["complete"] == 1
        assert r["partial"] == 1
        assert r["unmapped"] == 1


class TestNegativeTestCoverage:
    def test_full_negative_coverage(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], ["g.py"], ["a.json"], has_negative_tests=True)
        p.declare_section("D", ["t.py"], ["g.py"], ["a.json"], has_negative_tests=True)
        r = p.check_negative_test_coverage(["C", "D"])
        assert r["coverage_pct"] == 100.0

    def test_partial_negative_coverage(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], ["g.py"], ["a.json"], has_negative_tests=True)
        p.declare_section("D", ["t.py"], ["g.py"], ["a.json"], has_negative_tests=False)
        r = p.check_negative_test_coverage(["C", "D"])
        assert r["coverage_pct"] == 50.0


class TestDuplicateDetection:
    def test_no_duplicates(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["test_c.py"], ["g.py"], ["a.json"])
        p.declare_section("D", ["test_d.py"], ["g.py"], ["a.json"])
        r = p.check_duplicates(["C", "D"])
        assert not r["has_duplicates"]

    def test_shared_test_file_detected(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["test_shared.py"], ["g.py"], ["a.json"])
        p.declare_section("D", ["test_shared.py"], ["g.py"], ["a.json"])
        r = p.check_duplicates(["C", "D"])
        assert r["has_duplicates"]
        assert "test_shared.py" in r["duplicate_mappings"]


class TestConsolidatedReport:
    def test_passing_report(self):
        p = TestStrategyPolicy()
        for s in ["C", "D", "K", "L", "N", "T"]:
            p.declare_section(s, ["t.py"], ["g.py"], ["a.json"], has_negative_tests=True)
        r = p.get_strategy_report(["C", "D", "K", "L", "N", "T"])
        assert r["verdict"] == "PASS"
        assert r["completeness"]["all_complete"]

    def test_failing_report(self):
        p = TestStrategyPolicy()
        p.declare_section("C", ["t.py"], ["g.py"], ["a.json"])
        r = p.get_strategy_report(["C", "D"])
        assert r["verdict"] == "FAIL"
