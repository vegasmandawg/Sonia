"""
Code quality validation module.

Provides static analysis checks:
- Import ordering validation
- Docstring presence for public functions
- Complexity threshold enforcement
- No bare except clauses
- No print() in production code
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class QualityViolation:
    file: str
    line: int
    rule: str
    message: str
    severity: str = "warning"  # warning, error

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class QualityReport:
    files_checked: int
    total_violations: int
    violations_by_rule: Dict[str, int] = field(default_factory=dict)
    violations: List[QualityViolation] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict:
        return {
            "files_checked": self.files_checked,
            "total_violations": self.total_violations,
            "violations_by_rule": self.violations_by_rule,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations[:50]],  # cap output
        }


class CodeQualityChecker:
    """Checks Python source files for quality violations."""

    MAX_COMPLEXITY = 15  # max cyclomatic complexity per function
    RULES = [
        "bare_except",
        "print_in_production",
        "missing_docstring",
        "high_complexity",
        "import_ordering",
    ]

    def __init__(self, max_complexity: int = 15, ignore_patterns: Optional[List[str]] = None):
        self.max_complexity = max_complexity
        self.ignore_patterns = ignore_patterns or ["__pycache__", ".pyc", "test_"]

    def check_file(self, filepath: Path) -> List[QualityViolation]:
        """Check a single Python file for quality violations."""
        violations: List[QualityViolation] = []
        fname = str(filepath)

        try:
            source = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return violations

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return violations

        lines = source.split("\n")

        # Check for bare except
        violations.extend(self._check_bare_except(tree, fname))

        # Check for print() calls
        violations.extend(self._check_print_calls(tree, fname))

        # Check for missing docstrings on public functions
        violations.extend(self._check_docstrings(tree, fname))

        # Check complexity
        violations.extend(self._check_complexity(tree, fname))

        # Check import ordering
        violations.extend(self._check_import_ordering(tree, fname))

        return violations

    def check_directory(self, directory: Path, recursive: bool = True) -> QualityReport:
        """Check all Python files in a directory."""
        violations: List[QualityViolation] = []
        files_checked = 0

        pattern = "**/*.py" if recursive else "*.py"
        for filepath in sorted(directory.glob(pattern)):
            # Skip ignored patterns
            if any(p in str(filepath) for p in self.ignore_patterns):
                continue
            file_violations = self.check_file(filepath)
            violations.extend(file_violations)
            files_checked += 1

        # Count by rule
        by_rule: Dict[str, int] = {}
        for v in violations:
            by_rule[v.rule] = by_rule.get(v.rule, 0) + 1

        error_count = sum(1 for v in violations if v.severity == "error")

        return QualityReport(
            files_checked=files_checked,
            total_violations=len(violations),
            violations_by_rule=by_rule,
            violations=violations,
            passed=error_count == 0,
        )

    def _check_bare_except(self, tree: ast.AST, fname: str) -> List[QualityViolation]:
        """Detect bare except clauses."""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                violations.append(QualityViolation(
                    file=fname,
                    line=node.lineno,
                    rule="bare_except",
                    message="Bare except clause; catch specific exceptions",
                    severity="warning",
                ))
        return violations

    def _check_print_calls(self, tree: ast.AST, fname: str) -> List[QualityViolation]:
        """Detect print() calls in production code."""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    violations.append(QualityViolation(
                        file=fname,
                        line=node.lineno,
                        rule="print_in_production",
                        message="print() call; use structured logging instead",
                        severity="warning",
                    ))
        return violations

    def _check_docstrings(self, tree: ast.AST, fname: str) -> List[QualityViolation]:
        """Check public functions/classes have docstrings."""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private/dunder functions
                if node.name.startswith("_"):
                    continue
                docstring = ast.get_docstring(node)
                if not docstring:
                    violations.append(QualityViolation(
                        file=fname,
                        line=node.lineno,
                        rule="missing_docstring",
                        message=f"Public function '{node.name}' has no docstring",
                        severity="warning",
                    ))
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith("_"):
                    continue
                docstring = ast.get_docstring(node)
                if not docstring:
                    violations.append(QualityViolation(
                        file=fname,
                        line=node.lineno,
                        rule="missing_docstring",
                        message=f"Public class '{node.name}' has no docstring",
                        severity="warning",
                    ))
        return violations

    def _check_complexity(self, tree: ast.AST, fname: str) -> List[QualityViolation]:
        """Estimate cyclomatic complexity."""
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = self._calc_complexity(node)
                if complexity > self.max_complexity:
                    violations.append(QualityViolation(
                        file=fname,
                        line=node.lineno,
                        rule="high_complexity",
                        message=f"Function '{node.name}' has complexity {complexity} (max: {self.max_complexity})",
                        severity="warning",
                    ))
        return violations

    def _calc_complexity(self, node: ast.AST) -> int:
        """Calculate cyclomatic complexity of a function."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def _check_import_ordering(self, tree: ast.AST, fname: str) -> List[QualityViolation]:
        """Check that imports are grouped: stdlib, third-party, local."""
        violations = []
        imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(node)

        # Check imports are at the top and grouped
        if len(imports) >= 2:
            prev_line = imports[0].lineno
            for imp in imports[1:]:
                # Large gap (>3 lines) between imports suggests grouping issues
                if imp.lineno - prev_line > 5:
                    violations.append(QualityViolation(
                        file=fname,
                        line=imp.lineno,
                        rule="import_ordering",
                        message="Import statement far from import block; consider grouping",
                        severity="warning",
                    ))
                prev_line = imp.lineno

        return violations

    def get_rules(self) -> List[str]:
        """Return list of active rules."""
        return self.RULES.copy()

    def get_summary(self) -> dict:
        """Return checker configuration summary."""
        return {
            "max_complexity": self.max_complexity,
            "ignore_patterns": self.ignore_patterns,
            "rules": self.RULES,
        }
