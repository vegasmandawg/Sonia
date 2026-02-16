"""
Coverage Completeness Module
=============================
Machine-checkable mapping: each scorer section (A-Y) must map to:
  - At least one gate check
  - At least one test family
  - At least one evidence artifact pattern

Fails on unmapped or partially mapped controls.
Emits completeness percentage and missing map entries.
"""
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Any


# ---------------------------------------------------------------------------
# Section mapping data model
# ---------------------------------------------------------------------------

@dataclass
class SectionMapping:
    """Mapping for a single scorer section."""
    section_id: str
    section_name: str
    gates: List[str] = field(default_factory=list)
    test_families: List[str] = field(default_factory=list)
    artifact_patterns: List[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(self.gates) and bool(self.test_families) and bool(self.artifact_patterns)

    @property
    def missing_fields(self) -> List[str]:
        missing = []
        if not self.gates:
            missing.append("gates")
        if not self.test_families:
            missing.append("test_families")
        if not self.artifact_patterns:
            missing.append("artifact_patterns")
        return missing

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "section_name": self.section_name,
            "gates": self.gates,
            "test_families": self.test_families,
            "artifact_patterns": self.artifact_patterns,
            "is_complete": self.is_complete,
            "missing_fields": self.missing_fields,
        }


# ---------------------------------------------------------------------------
# Full section registry (A-Y, 25 sections)
# ---------------------------------------------------------------------------

SECTION_NAMES = {
    "A": "Architecture & Design",
    "B": "API Contracts",
    "C": "Code Quality",
    "D": "Configuration Management",
    "E": "Error Handling",
    "F": "Fault Tolerance",
    "G": "Gate Coverage",
    "H": "Health Checks",
    "I": "Integration Testing",
    "J": "Data Management",
    "K": "Performance",
    "L": "Contract Consistency",
    "M": "Store Durability",
    "N": "Observability",
    "O": "Operational Readiness",
    "P": "Process Maturity",
    "Q": "Privacy & Compliance",
    "R": "Recovery",
    "S": "CI/CD Automation",
    "T": "Test Strategy",
    "U": "Upgrade Path",
    "V": "Versioning",
    "W": "Documentation",
    "X": "External Integration",
    "Y": "Year-over-year Stability",
}

# Gate-to-section mapping (which gates cover which sections)
GATE_SECTION_MAP: Dict[str, List[str]] = {
    "auth-posture-gate.py": ["A", "Q"],
    "auth-surface-gate.py": ["A", "B", "Q"],
    "backup-restore-drill.py": ["M", "R"],
    "cleanroom-parity-gate.py": ["P", "V"],
    "consolidated-preaudit.py": ["G", "I", "P"],
    "drill-determinism-gate.py": ["F", "R"],
    "fallback-behavior-gate.py": ["E", "F"],
    "incident-bundle-gate.py": ["N", "O"],
    "incident-completeness-gate.py": ["N", "O"],
    "incident-lineage-gate.py": ["J", "N"],
    "memory-silo-gate.py": ["J", "M"],
    "output-budget-gate.py": ["K", "E"],
    "perf-budget-gate.py": ["K"],
    "policy-enforcement-gate.py": ["C", "Q"],
    "rate-limiter-gate.py": ["K", "F"],
    "recovery-determinism-gate.py": ["R", "F"],
    "regression-guard-gate.py": ["I", "T"],
    "release-integrity-gate.py": ["P", "V"],
    "restore-integrity-gate.py": ["M", "R"],
    "runtime-qos-gate.py": ["K", "H"],
    "secret-scan-gate.py": ["Q", "C"],
    "session-isolation-gate.py": ["A", "F"],
    "traceability-gate.py": ["N", "L"],
    "unit-test-layer-gate.py": ["T", "I"],
    "schema-validation-gate.py": ["D", "J"],
    "data-migration-gate.py": ["J", "U"],
    "automation-coverage-gate.py": ["S", "G"],
    "trace-propagation-gate.py": ["N", "L", "K"],
    "coverage-completeness-gate.py": ["S", "G", "T", "W"],
    "data-durability-gate.py": ["M", "J", "R"],
}

# Test family to section mapping
TEST_SECTION_MAP: Dict[str, List[str]] = {
    "test_auth": ["A", "Q"],
    "test_action_pipeline": ["A", "B", "E"],
    "test_backup": ["M", "R"],
    "test_breaker": ["F", "R"],
    "test_config_schema": ["D", "J"],
    "test_data_schema": ["D", "J"],
    "test_migration_policy": ["J", "U"],
    "test_code_quality": ["C"],
    "test_dlq": ["N", "R"],
    "test_fallback": ["E", "F"],
    "test_memory": ["J", "M"],
    "test_model_routing": ["B", "L"],
    "test_operator": ["O", "W"],
    "test_perf_profile": ["K"],
    "test_perception": ["N", "X"],
    "test_privacy": ["Q"],
    "test_recovery": ["R", "F"],
    "test_session": ["A", "H"],
    "test_stage": ["I", "T"],
    "test_stream": ["B", "E"],
    "test_supervision": ["H", "O"],
    "test_tool": ["E", "F"],
    "test_trace": ["N", "L"],
    "test_automation_coverage": ["S", "G"],
    "test_test_coverage": ["T", "I"],
    "test_data_durability": ["M", "J", "R"],
    "test_coverage_completeness": ["S", "G", "T"],
    "test_epic1_section_closure": ["J", "S", "M", "O", "Q", "W"],
}

# Artifact patterns to section mapping
ARTIFACT_SECTION_MAP: Dict[str, List[str]] = {
    "auth-posture-gate-*.json": ["A", "Q"],
    "auth-surface-gate-*.json": ["A", "B"],
    "backup-restore-*.json": ["M", "R"],
    "cleanroom-parity-*.json": ["P", "V"],
    "consolidated-preaudit-*.json": ["G", "I"],
    "drill-determinism-*.json": ["F", "R"],
    "fallback-behavior-*.json": ["E", "F"],
    "incident-*-gate-*.json": ["N", "O"],
    "memory-silo-*.json": ["J", "M"],
    "output-budget-*.json": ["K", "E"],
    "perf-budget-*.json": ["K"],
    "policy-enforcement-*.json": ["C", "Q"],
    "rate-limiter-*.json": ["K", "F"],
    "recovery-determinism-*.json": ["R", "F"],
    "regression-guard-*.json": ["I", "T"],
    "release-integrity-*.json": ["P", "V"],
    "restore-integrity-*.json": ["M", "R"],
    "runtime-qos-*.json": ["K", "H"],
    "secret-scan-*.json": ["Q", "C"],
    "session-isolation-*.json": ["A", "F"],
    "traceability-*.json": ["N", "L"],
    "unit-test-layer-*.json": ["T", "I"],
    "schema-validation-*.json": ["D", "J"],
    "data-migration-*.json": ["J", "U"],
    "automation-coverage-*.json": ["S", "G"],
    "trace-propagation-*.json": ["N", "L", "K"],
    "coverage-completeness-*.json": ["S", "G", "T", "W"],
    "data-durability-*.json": ["M", "J", "R"],
    "gate-matrix-*.json": ["P", "S"],
    "unit-summary-*.json": ["T", "I"],
    "*-scorecard-*.json": ["P", "G"],
    "deduction-sweep-*.json": ["C", "D", "K", "L", "N", "T"],
    "test-strategy-*.json": ["T", "I", "S"],
}


# ---------------------------------------------------------------------------
# Coverage analyzer
# ---------------------------------------------------------------------------

class CoverageCompletenessAnalyzer:
    """Analyzes section coverage across gates, tests, and artifacts."""

    def __init__(
        self,
        gate_map: Optional[Dict[str, List[str]]] = None,
        test_map: Optional[Dict[str, List[str]]] = None,
        artifact_map: Optional[Dict[str, List[str]]] = None,
    ):
        self.gate_map = gate_map if gate_map is not None else GATE_SECTION_MAP
        self.test_map = test_map if test_map is not None else TEST_SECTION_MAP
        self.artifact_map = artifact_map if artifact_map is not None else ARTIFACT_SECTION_MAP

    def build_section_mappings(self) -> Dict[str, SectionMapping]:
        """Build complete mapping for all 25 sections."""
        mappings: Dict[str, SectionMapping] = {}

        for sid, name in SECTION_NAMES.items():
            mappings[sid] = SectionMapping(section_id=sid, section_name=name)

        # Populate gates
        for gate, sections in self.gate_map.items():
            for s in sections:
                if s in mappings:
                    mappings[s].gates.append(gate)

        # Populate test families
        for test_fam, sections in self.test_map.items():
            for s in sections:
                if s in mappings:
                    mappings[s].test_families.append(test_fam)

        # Populate artifact patterns
        for pattern, sections in self.artifact_map.items():
            for s in sections:
                if s in mappings:
                    mappings[s].artifact_patterns.append(pattern)

        return mappings

    def check_completeness(
        self, target_sections: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Check coverage completeness. If target_sections given, only check those."""
        mappings = self.build_section_mappings()
        sections_to_check = target_sections or list(SECTION_NAMES.keys())

        complete = []
        incomplete = []
        missing_details: Dict[str, List[str]] = {}

        for sid in sections_to_check:
            m = mappings.get(sid)
            if m is None:
                incomplete.append(sid)
                missing_details[sid] = ["section not found in registry"]
                continue
            if m.is_complete:
                complete.append(sid)
            else:
                incomplete.append(sid)
                missing_details[sid] = m.missing_fields

        total = len(sections_to_check)
        pct = round(len(complete) / total * 100, 1) if total > 0 else 0.0

        return {
            "total_sections": total,
            "complete": len(complete),
            "incomplete": len(incomplete),
            "completeness_pct": pct,
            "complete_sections": complete,
            "incomplete_sections": incomplete,
            "missing_details": missing_details,
            "mappings": {sid: mappings[sid].to_dict() for sid in sections_to_check},
        }

    def check_target_sections(self, target_sections: List[str]) -> Dict[str, Any]:
        """Check only the target sections and fail on any incomplete."""
        result = self.check_completeness(target_sections)
        result["all_targets_complete"] = result["incomplete"] == 0
        return result

    def emit_artifact(self, output_dir: str, target_sections: Optional[List[str]] = None) -> str:
        """Emit completeness report artifact."""
        result = self.check_completeness(target_sections)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = out / f"coverage-completeness-{ts}.json"
        path.write_text(json.dumps(result, indent=2))
        return str(path)
