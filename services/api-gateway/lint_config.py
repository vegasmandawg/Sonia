"""
Lint/Type/Style Policy Configuration (Section C: Code Quality)
===============================================================
Enforces code quality evidence through policy declarations,
not ad-hoc checks. Provides deterministic lint rule inventory.
"""
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class LintRule:
    rule_id: str
    description: str
    severity: Severity
    enabled: bool = True
    category: str = "general"


@dataclass
class LintConfig:
    """Canonical lint policy configuration."""
    name: str = "sonia-lint-policy"
    version: str = "1.0.0"
    rules: List[LintRule] = field(default_factory=list)
    type_checking_enabled: bool = True
    style_guide: str = "pep8"
    max_line_length: int = 120
    max_complexity: int = 15

    def add_rule(self, rule: LintRule) -> None:
        self.rules.append(rule)

    def get_enabled_rules(self) -> List[LintRule]:
        return [r for r in self.rules if r.enabled]

    def get_rules_by_severity(self, severity: Severity) -> List[LintRule]:
        return [r for r in self.rules if r.severity == severity and r.enabled]

    def validate(self) -> Dict[str, Any]:
        """Validate the lint config itself."""
        issues = []
        if not self.rules:
            issues.append("No lint rules defined")
        if self.max_complexity < 1:
            issues.append("max_complexity must be >= 1")
        if self.max_line_length < 40:
            issues.append("max_line_length must be >= 40")
        error_rules = self.get_rules_by_severity(Severity.ERROR)
        if not error_rules:
            issues.append("No error-severity rules defined")
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "rule_count": len(self.rules),
            "enabled_count": len(self.get_enabled_rules()),
            "error_rules": len(error_rules),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "type_checking_enabled": self.type_checking_enabled,
            "style_guide": self.style_guide,
            "max_line_length": self.max_line_length,
            "max_complexity": self.max_complexity,
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "description": r.description,
                    "severity": r.severity.value,
                    "enabled": r.enabled,
                    "category": r.category,
                }
                for r in self.rules
            ],
        }


# Default SONIA lint policy
DEFAULT_POLICY = LintConfig(
    rules=[
        LintRule("no-bare-except", "Disallow bare except clauses", Severity.ERROR, category="safety"),
        LintRule("no-print", "Disallow print() in production code", Severity.WARNING, category="quality"),
        LintRule("require-docstring", "Require docstrings on public functions", Severity.WARNING, category="docs"),
        LintRule("max-complexity", "Enforce cyclomatic complexity limit", Severity.ERROR, category="complexity"),
        LintRule("type-annotations", "Require type annotations on public APIs", Severity.WARNING, category="types"),
        LintRule("no-hardcoded-secrets", "Disallow hardcoded credentials", Severity.ERROR, category="security"),
        LintRule("import-order", "Enforce import ordering (stdlib, third-party, local)", Severity.INFO, category="style"),
    ]
)
