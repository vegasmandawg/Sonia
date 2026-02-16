"""
Unit tests for code_quality.py — CodeQualityChecker.

Covers:
- Bare except detection
- Print call detection
- Missing docstring detection
- Complexity threshold enforcement
- Import ordering validation
- Directory checking
- Configuration and summary
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"S:\services\api-gateway")

from code_quality import CodeQualityChecker, QualityViolation, QualityReport


def _write_temp_py(content: str) -> Path:
    """Write content to a temp .py file and return path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    f.write(content)
    f.flush()
    f.close()
    return Path(f.name)


class TestCodeQualityChecker:
    """Tests for CodeQualityChecker."""

    def test_clean_file_no_violations(self):
        src = '''
"""Module docstring."""

def greet(name: str) -> str:
    """Say hello."""
    return f"Hello {name}"
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert len(violations) == 0

    def test_bare_except_detected(self):
        src = '''
def risky():
    """Do something risky."""
    try:
        pass
    except:
        pass
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert any(v.rule == "bare_except" for v in violations)

    def test_print_call_detected(self):
        src = '''
def debug():
    """Debug function."""
    print("debug output")
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert any(v.rule == "print_in_production" for v in violations)

    def test_missing_docstring_public_function(self):
        src = '''
def public_function():
    pass
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert any(v.rule == "missing_docstring" for v in violations)

    def test_missing_docstring_public_class(self):
        src = '''
class PublicClass:
    pass
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert any(v.rule == "missing_docstring" and "PublicClass" in v.message for v in violations)

    def test_private_function_no_docstring_ok(self):
        src = '''
def _private():
    pass
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert not any(v.rule == "missing_docstring" for v in violations)

    def test_high_complexity_detected(self):
        # Generate a function with many branches
        branches = "\n".join(f"    if x == {i}: return {i}" for i in range(20))
        src = f'''
def complex_func(x):
    """Complex function."""
{branches}
'''
        checker = CodeQualityChecker(max_complexity=5)
        violations = checker.check_file(_write_temp_py(src))
        assert any(v.rule == "high_complexity" for v in violations)

    def test_low_complexity_ok(self):
        src = '''
def simple(x):
    """Simple function."""
    if x > 0:
        return x
    return -x
'''
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert not any(v.rule == "high_complexity" for v in violations)

    def test_custom_max_complexity(self):
        checker = CodeQualityChecker(max_complexity=3)
        assert checker.max_complexity == 3

    def test_syntax_error_file_returns_empty(self):
        src = "def broken(:\n    pass"
        checker = CodeQualityChecker()
        violations = checker.check_file(_write_temp_py(src))
        assert violations == []

    def test_nonexistent_file_returns_empty(self):
        checker = CodeQualityChecker()
        violations = checker.check_file(Path("/nonexistent/file.py"))
        assert violations == []

    def test_check_directory(self):
        import os
        tmpdir = Path(tempfile.mkdtemp())
        (tmpdir / "good.py").write_text('"""Good."""\n\ndef foo():\n    """Foo."""\n    pass\n', encoding="utf-8")
        (tmpdir / "bad.py").write_text('def bar():\n    print("x")\n', encoding="utf-8")

        checker = CodeQualityChecker()
        report = checker.check_directory(tmpdir, recursive=False)
        assert report.files_checked == 2
        assert report.total_violations > 0
        assert isinstance(report.violations_by_rule, dict)

    def test_ignore_patterns(self):
        checker = CodeQualityChecker(ignore_patterns=["test_"])
        assert "test_" in checker.ignore_patterns

    def test_get_rules(self):
        checker = CodeQualityChecker()
        rules = checker.get_rules()
        assert "bare_except" in rules
        assert "print_in_production" in rules
        assert "missing_docstring" in rules
        assert "high_complexity" in rules
        assert "import_ordering" in rules

    def test_get_summary(self):
        checker = CodeQualityChecker(max_complexity=10)
        summary = checker.get_summary()
        assert summary["max_complexity"] == 10
        assert "rules" in summary

    def test_violation_to_dict(self):
        v = QualityViolation(file="test.py", line=10, rule="bare_except", message="test msg")
        d = v.to_dict()
        assert d["file"] == "test.py"
        assert d["line"] == 10
        assert d["rule"] == "bare_except"

    def test_report_to_dict(self):
        report = QualityReport(files_checked=2, total_violations=1, passed=True)
        d = report.to_dict()
        assert d["files_checked"] == 2
        assert d["passed"] is True

    def test_report_caps_violations(self):
        """Report.to_dict caps at 50 violations."""
        vs = [QualityViolation(file="f.py", line=i, rule="test", message="m") for i in range(60)]
        report = QualityReport(files_checked=1, total_violations=60, violations=vs)
        d = report.to_dict()
        assert len(d["violations"]) == 50
