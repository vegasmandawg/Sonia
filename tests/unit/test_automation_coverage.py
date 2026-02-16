"""
Unit tests for automation_coverage.py — AutomationCoverageAnalyzer.

Covers:
- Gate scanning from directories
- Section mapping
- Coverage gap detection
- Artifact verification
- Summary output
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\api-gateway")

from automation_coverage import (
    AutomationCoverageAnalyzer,
    CoverageReport,
    GateInfo,
    GATE_SECTION_MAP,
    ALL_SECTIONS,
)


def _mock_gate_dir() -> Path:
    """Create a temp dir with mock gate files."""
    d = Path(tempfile.mkdtemp())
    (d / "api-contract-gate.py").write_text("# gate", encoding="utf-8")
    (d / "config-schema-gate.py").write_text("# gate", encoding="utf-8")
    (d / "auth-posture-gate.py").write_text("# gate", encoding="utf-8")
    return d


class TestAutomationCoverageAnalyzer:
    """Tests for AutomationCoverageAnalyzer."""

    def test_scan_gates_discovers_files(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        gates = analyzer.scan_gates()
        assert len(gates) == 3
        names = [g.name for g in gates]
        assert "api-contract-gate.py" in names

    def test_scan_gates_skips_nonexistent_dir(self):
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[Path("/nonexistent")])
        gates = analyzer.scan_gates()
        assert gates == []

    def test_section_mapping(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        gates = analyzer.scan_gates()
        api_gate = [g for g in gates if g.name == "api-contract-gate.py"][0]
        assert "A" in api_gate.sections

    def test_coverage_report_structure(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        report = analyzer.analyze_coverage()
        assert report.total_gates == 3
        assert report.total_sections == 25
        assert len(report.covered_sections) > 0
        assert report.coverage_ratio > 0

    def test_uncovered_sections_detected(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        report = analyzer.analyze_coverage()
        # Only 3 gates covering A, B, C, E — many sections uncovered
        assert len(report.uncovered_sections) > 0

    def test_get_gaps(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        gaps = analyzer.get_gaps()
        assert isinstance(gaps, list)
        assert len(gaps) > 0

    def test_full_coverage_no_gaps(self):
        """With all gates present, coverage should be near complete."""
        d = _mock_gate_dir()
        # Add all known gates
        for gate_name in GATE_SECTION_MAP:
            (d / gate_name).write_text("# gate", encoding="utf-8")
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        report = analyzer.analyze_coverage()
        assert report.coverage_ratio > 0.9

    def test_artifact_verification(self):
        d = _mock_gate_dir()
        artifact_dir = Path(tempfile.mkdtemp())
        # Create a fake artifact
        (artifact_dir / "api-contract-gate-20260215.json").write_text("{}", encoding="utf-8")
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        result = analyzer.verify_artifact_production(artifact_dir)
        assert result["api-contract-gate.py"] is True
        assert result["config-schema-gate.py"] is False

    def test_gate_info_to_dict(self):
        g = GateInfo(name="test-gate.py", path="/tmp/test-gate.py", sections=["A"])
        d = g.to_dict()
        assert d["name"] == "test-gate.py"
        assert "A" in d["sections"]

    def test_coverage_report_to_dict(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        report = analyzer.analyze_coverage()
        rd = report.to_dict()
        assert "total_gates" in rd
        assert "coverage_ratio" in rd
        assert "gates" in rd

    def test_get_summary(self):
        d = _mock_gate_dir()
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d])
        summary = analyzer.get_summary()
        assert "total_gates" in summary
        assert "coverage_ratio" in summary
        assert "gap_sections" in summary

    def test_dedup_across_dirs(self):
        """Gates with same name in multiple dirs should be deduped."""
        d1 = _mock_gate_dir()
        d2 = Path(tempfile.mkdtemp())
        (d2 / "api-contract-gate.py").write_text("# dup", encoding="utf-8")
        analyzer = AutomationCoverageAnalyzer(gate_dirs=[d1, d2])
        gates = analyzer.scan_gates()
        names = [g.name for g in gates]
        assert names.count("api-contract-gate.py") == 1
