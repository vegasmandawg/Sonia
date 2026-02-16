"""
Unit tests for test_coverage.py — TestCoverageAnalyzer.

Covers:
- Module enumeration
- Test file enumeration
- Module-to-test mapping
- Coverage ratio computation
- Untested module detection
- Trend tracking
- Summary output
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\api-gateway")

from test_coverage import (
    TestCoverageAnalyzer,
    CoverageSnapshot,
    ModuleTestMapping,
)


def _mock_project() -> tuple:
    """Create mock source and test directories."""
    src = Path(tempfile.mkdtemp())
    tests = Path(tempfile.mkdtemp())

    # Source modules
    (src / "main.py").write_text("# main", encoding="utf-8")
    (src / "router.py").write_text("# router", encoding="utf-8")
    (src / "auth.py").write_text("# auth", encoding="utf-8")
    (src / "__init__.py").write_text("", encoding="utf-8")

    # Test files (only main and router have tests)
    (tests / "test_main.py").write_text("# test", encoding="utf-8")
    (tests / "test_router.py").write_text("# test", encoding="utf-8")

    return src, tests


class TestTestCoverageAnalyzer:
    """Tests for TestCoverageAnalyzer."""

    def test_enumerate_modules(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        modules = analyzer.enumerate_modules()
        names = [m.name for m in modules]
        assert "main.py" in names
        assert "router.py" in names
        assert "__init__.py" not in names  # excluded

    def test_enumerate_tests(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        test_files = analyzer.enumerate_tests()
        names = [t.name for t in test_files]
        assert "test_main.py" in names
        assert "test_router.py" in names

    def test_map_module_to_test(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        assert analyzer.map_module_to_test("main.py") is not None
        assert analyzer.map_module_to_test("auth.py") is None

    def test_analyze_coverage(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        snapshot = analyzer.analyze()
        assert snapshot.total_modules == 3  # main, router, auth (not __init__)
        assert snapshot.tested_modules == 2
        assert snapshot.untested_modules == 1
        assert snapshot.coverage_ratio > 0.6

    def test_untested_list(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        untested = analyzer.get_untested()
        assert "auth.py" in untested

    def test_full_coverage(self):
        src, tests = _mock_project()
        # Add missing test
        (tests / "test_auth.py").write_text("# test", encoding="utf-8")
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        snapshot = analyzer.analyze()
        assert snapshot.coverage_ratio == 1.0
        assert snapshot.untested_modules == 0

    def test_no_modules(self):
        src = Path(tempfile.mkdtemp())
        tests = Path(tempfile.mkdtemp())
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        snapshot = analyzer.analyze()
        assert snapshot.total_modules == 0
        assert snapshot.coverage_ratio == 0.0

    def test_nonexistent_dirs(self):
        analyzer = TestCoverageAnalyzer(
            source_dir=Path("/nonexistent/src"),
            test_dir=Path("/nonexistent/tests"),
        )
        assert analyzer.enumerate_modules() == []
        assert analyzer.enumerate_tests() == []

    def test_trend_tracking(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        analyzer.analyze()
        # Add a test and re-analyze
        (tests / "test_auth.py").write_text("# test", encoding="utf-8")
        analyzer.analyze()
        trend = analyzer.get_trend()
        assert len(trend) == 2
        assert trend[1]["ratio"] > trend[0]["ratio"]

    def test_snapshot_to_dict(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        snapshot = analyzer.analyze()
        d = snapshot.to_dict()
        assert "total_modules" in d
        assert "coverage_ratio" in d
        assert "mappings" in d
        assert "untested_list" in d

    def test_mapping_to_dict(self):
        m = ModuleTestMapping(
            module="main.py",
            module_path="/src/main.py",
            test_file="test_main.py",
            has_test=True,
        )
        d = m.to_dict()
        assert d["module"] == "main.py"
        assert d["has_test"] is True

    def test_get_summary(self):
        src, tests = _mock_project()
        analyzer = TestCoverageAnalyzer(source_dir=src, test_dir=tests)
        summary = analyzer.get_summary()
        assert "total_modules" in summary
        assert "coverage_ratio" in summary
        assert "untested_count" in summary
