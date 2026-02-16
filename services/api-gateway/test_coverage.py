"""
Test coverage analyzer for audit evidence.

Provides:
- Source module enumeration in services/api-gateway/
- Test file mapping from tests/unit/
- Coverage ratio computation
- Untested module identification
- Coverage trend tracking
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass
class ModuleTestMapping:
    module: str
    module_path: str
    test_file: Optional[str] = None
    test_path: Optional[str] = None
    has_test: bool = False

    def to_dict(self) -> dict:
        return {
            "module": self.module,
            "module_path": self.module_path,
            "test_file": self.test_file,
            "test_path": self.test_path,
            "has_test": self.has_test,
        }


@dataclass
class CoverageSnapshot:
    total_modules: int
    tested_modules: int
    untested_modules: int
    coverage_ratio: float
    mappings: List[ModuleTestMapping] = field(default_factory=list)
    untested_list: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_modules": self.total_modules,
            "tested_modules": self.tested_modules,
            "untested_modules": self.untested_modules,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "mappings": [m.to_dict() for m in self.mappings],
            "untested_list": self.untested_list,
        }


class TestCoverageAnalyzer:
    """Analyzes test coverage by mapping source modules to test files."""

    # Modules that don't need dedicated test files
    EXCLUDED_MODULES = {
        "__init__.py",
        "__main__.py",
        "conftest.py",
    }

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        test_dir: Optional[Path] = None,
        exclude_patterns: Optional[List[str]] = None,
    ):
        self.source_dir = source_dir or Path(r"S:\services\api-gateway")
        self.test_dir = test_dir or Path(r"S:\tests\unit")
        self.exclude_patterns = exclude_patterns or ["__pycache__"]
        self._snapshots: List[CoverageSnapshot] = []

    def enumerate_modules(self) -> List[Path]:
        """Find all Python source modules in the source directory."""
        if not self.source_dir.exists():
            return []
        modules = []
        for f in sorted(self.source_dir.glob("*.py")):
            if f.name in self.EXCLUDED_MODULES:
                continue
            if any(p in str(f) for p in self.exclude_patterns):
                continue
            modules.append(f)
        return modules

    def enumerate_tests(self) -> List[Path]:
        """Find all test files in the test directory."""
        if not self.test_dir.exists():
            return []
        return sorted(self.test_dir.glob("test_*.py"))

    def map_module_to_test(self, module_name: str) -> Optional[Path]:
        """Find the test file for a given module name."""
        # Convention: module.py -> test_module.py
        test_name = f"test_{module_name}"
        test_path = self.test_dir / test_name
        if test_path.exists():
            return test_path
        return None

    def analyze(self) -> CoverageSnapshot:
        """Perform coverage analysis."""
        modules = self.enumerate_modules()
        tests = {t.name for t in self.enumerate_tests()}
        mappings: List[ModuleTestMapping] = []
        tested = 0
        untested_list: List[str] = []

        for mod in modules:
            test_name = f"test_{mod.name}"
            test_path = self.test_dir / test_name
            has_test = test_name in tests

            mappings.append(ModuleTestMapping(
                module=mod.name,
                module_path=str(mod),
                test_file=test_name if has_test else None,
                test_path=str(test_path) if has_test else None,
                has_test=has_test,
            ))

            if has_test:
                tested += 1
            else:
                untested_list.append(mod.name)

        total = len(modules)
        ratio = tested / total if total > 0 else 0.0

        snapshot = CoverageSnapshot(
            total_modules=total,
            tested_modules=tested,
            untested_modules=total - tested,
            coverage_ratio=ratio,
            mappings=mappings,
            untested_list=untested_list,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def get_untested(self) -> List[str]:
        """Return list of modules without test files."""
        snapshot = self.analyze()
        return snapshot.untested_list

    def get_trend(self) -> List[dict]:
        """Return coverage trend from all snapshots taken."""
        return [
            {
                "index": i,
                "total": s.total_modules,
                "tested": s.tested_modules,
                "ratio": s.coverage_ratio,
            }
            for i, s in enumerate(self._snapshots)
        ]

    def get_summary(self) -> dict:
        """Return coverage summary."""
        snapshot = self.analyze()
        return {
            "total_modules": snapshot.total_modules,
            "tested_modules": snapshot.tested_modules,
            "coverage_ratio": snapshot.coverage_ratio,
            "untested_count": snapshot.untested_modules,
        }
