"""
Automation coverage analyzer for audit gates.

Provides:
- Enumeration of all gate scripts in scripts/gates/ and scripts/release/
- Mapping of gates to audit sections (A-Y)
- Section coverage gap detection
- JSON artifact verification
- Local runner completeness proof
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# Gate-to-section mapping (known gates -> audit sections they cover)
GATE_SECTION_MAP: Dict[str, List[str]] = {
    # Inherited gates (from v3.7 and earlier)
    "api-contract-gate.py": ["A"],
    "config-schema-gate.py": ["B", "C"],
    "auth-posture-gate.py": ["E"],
    "identity-scope-gate.py": ["F"],
    "memory-ledger-gate.py": ["G"],
    "perception-bridge-gate.py": ["H"],
    "model-routing-gate.py": ["I"],
    "data-integrity-gate.py": ["J"],
    "rate-limiter-gate.py": ["K"],
    "session-isolation-gate.py": ["L"],
    "tool-policy-gate.py": ["M"],
    "turn-quality-gate.py": ["N"],
    "fallback-behavior-gate.py": ["O"],
    "log-redaction-gate.py": ["P"],
    "backup-restore-gate.py": ["Q"],
    "recovery-policy-gate.py": ["R"],
    "runtime-qos-gate.py": ["S"],
    "unit-test-layer-gate.py": ["T"],
    "output-budget-gate.py": ["U"],
    "drill-determinism-gate.py": ["V"],
    "dlq-replay-gate.py": ["W"],
    "memory-silo-gate.py": ["X"],
    "policy-enforcement-gate.py": ["Y"],
    # Delta gates (v3.8)
    "schema-validation-gate.py": ["C", "D", "J"],
    "data-migration-gate.py": ["D", "J"],
    "automation-coverage-gate.py": ["S"],
    "trace-propagation-gate.py": ["N"],
}

ALL_SECTIONS = list("ABCDEFGHIJKLMNOPQRSTUVWXY")


@dataclass
class GateInfo:
    name: str
    path: str
    sections: List[str]
    has_artifact: bool = False
    executable: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "sections": self.sections,
            "has_artifact": self.has_artifact,
            "executable": self.executable,
        }


@dataclass
class CoverageReport:
    total_gates: int
    total_sections: int
    covered_sections: List[str]
    uncovered_sections: List[str]
    coverage_ratio: float
    gates: List[GateInfo] = field(default_factory=list)
    section_gate_count: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_gates": self.total_gates,
            "total_sections": self.total_sections,
            "covered_sections": self.covered_sections,
            "uncovered_sections": self.uncovered_sections,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "gates": [g.to_dict() for g in self.gates],
            "section_gate_count": self.section_gate_count,
        }


class AutomationCoverageAnalyzer:
    """Analyzes gate coverage across audit sections."""

    def __init__(
        self,
        gate_dirs: Optional[List[Path]] = None,
        section_map: Optional[Dict[str, List[str]]] = None,
    ):
        self.gate_dirs = gate_dirs or [
            Path(r"S:\scripts\gates"),
            Path(r"S:\scripts\release"),
        ]
        self.section_map = section_map or GATE_SECTION_MAP

    def scan_gates(self) -> List[GateInfo]:
        """Discover all gate scripts in configured directories."""
        gates: List[GateInfo] = []
        seen: Set[str] = set()

        for gate_dir in self.gate_dirs:
            if not gate_dir.exists():
                continue
            for f in sorted(gate_dir.glob("*-gate.py")):
                if f.name in seen:
                    continue
                seen.add(f.name)
                sections = self.section_map.get(f.name, [])
                gates.append(GateInfo(
                    name=f.name,
                    path=str(f),
                    sections=sections,
                    executable=f.is_file(),
                ))
        return gates

    def analyze_coverage(self) -> CoverageReport:
        """Analyze section coverage from discovered gates."""
        gates = self.scan_gates()
        covered: Set[str] = set()
        section_count: Dict[str, int] = {s: 0 for s in ALL_SECTIONS}

        for gate in gates:
            for section in gate.sections:
                covered.add(section)
                if section in section_count:
                    section_count[section] += 1

        covered_list = sorted(covered)
        uncovered_list = [s for s in ALL_SECTIONS if s not in covered]
        ratio = len(covered_list) / len(ALL_SECTIONS) if ALL_SECTIONS else 0.0

        return CoverageReport(
            total_gates=len(gates),
            total_sections=len(ALL_SECTIONS),
            covered_sections=covered_list,
            uncovered_sections=uncovered_list,
            coverage_ratio=ratio,
            gates=gates,
            section_gate_count=section_count,
        )

    def get_gaps(self) -> List[str]:
        """Return sections with no gate coverage."""
        report = self.analyze_coverage()
        return report.uncovered_sections

    def verify_artifact_production(self, artifact_dir: Path) -> Dict[str, bool]:
        """Check which gates have produced JSON artifacts."""
        gates = self.scan_gates()
        result: Dict[str, bool] = {}
        for gate in gates:
            stem = gate.name.replace(".py", "")
            has = any(artifact_dir.glob(f"{stem}-*.json"))
            result[gate.name] = has
        return result

    def get_summary(self) -> dict:
        """Return analysis summary."""
        report = self.analyze_coverage()
        return {
            "total_gates": report.total_gates,
            "coverage_ratio": report.coverage_ratio,
            "covered": len(report.covered_sections),
            "uncovered": len(report.uncovered_sections),
            "gap_sections": report.uncovered_sections,
        }
