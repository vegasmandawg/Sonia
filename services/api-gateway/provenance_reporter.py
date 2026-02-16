"""
Provenance Reporter: Deterministic summary export.
====================================================
Produces governance audit completeness reports by combining
provenance registry, lineage mapper, and evidence integrity data.

All operations are deterministic: same inputs always produce
identical output (same JSON, same hashes, same ordering).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from provenance_registry import ProvenanceRegistry
from lineage_mapper import LineageMapper
from evidence_integrity import EvidenceIntegrityChecker


@dataclass
class ProvenanceReport:
    """Immutable governance audit report."""
    version: str
    timestamp_utc: str
    registry_manifest: Dict
    lineage_completeness: Dict
    evidence_audit: Dict
    overall_verdict: str  # "PASS" or "FAIL"
    report_hash: str  # SHA-256 of the canonical JSON

    def to_dict(self) -> Dict:
        return {
            "version": self.version,
            "timestamp_utc": self.timestamp_utc,
            "registry_manifest": self.registry_manifest,
            "lineage_completeness": self.lineage_completeness,
            "evidence_audit": self.evidence_audit,
            "overall_verdict": self.overall_verdict,
            "report_hash": self.report_hash,
        }


class ProvenanceReporter:
    """
    Combines registry, lineage, and evidence data into a single
    deterministic audit report.
    """

    def __init__(
        self,
        registry: ProvenanceRegistry,
        mapper: LineageMapper,
        checker: EvidenceIntegrityChecker,
        version: str = "4.1.0-dev",
    ):
        self._registry = registry
        self._mapper = mapper
        self._checker = checker
        self._version = version

    def generate(self, timestamp_utc: Optional[str] = None) -> ProvenanceReport:
        """
        Generate a complete provenance audit report.

        If timestamp_utc is not provided, uses current UTC time.
        For deterministic testing, always pass a fixed timestamp.
        """
        if timestamp_utc is None:
            timestamp_utc = datetime.now(timezone.utc).isoformat()

        registry_manifest = self._registry.export_manifest()
        lineage_completeness = self._mapper.completeness_report()
        evidence_audit = self._checker.full_audit()

        # Determine overall verdict
        lineage_ok = lineage_completeness["completeness_pct"] == 100.0
        evidence_ok = evidence_audit.get("overall_pass", False)
        registry_ok = len(self._registry.check_uniqueness()) == 0

        overall = "PASS" if (lineage_ok and evidence_ok and registry_ok) else "FAIL"

        # Compute deterministic hash of the report content
        content_for_hash = {
            "version": self._version,
            "timestamp_utc": timestamp_utc,
            "registry_hash": registry_manifest.get("manifest_hash", ""),
            "lineage_completeness_pct": lineage_completeness["completeness_pct"],
            "evidence_pass": evidence_audit.get("overall_pass", False),
            "verdict": overall,
        }
        canonical = json.dumps(content_for_hash, sort_keys=True, separators=(",", ":"))
        report_hash = hashlib.sha256(canonical.encode()).hexdigest()

        return ProvenanceReport(
            version=self._version,
            timestamp_utc=timestamp_utc,
            registry_manifest=registry_manifest,
            lineage_completeness=lineage_completeness,
            evidence_audit=evidence_audit,
            overall_verdict=overall,
            report_hash=report_hash,
        )

    def verify_rerun_parity(self, report1: ProvenanceReport, report2: ProvenanceReport) -> bool:
        """
        Verify that two reports generated from the same state have the same hash.
        This proves deterministic re-run parity.
        """
        return report1.report_hash == report2.report_hash

    def export_json(self, report: ProvenanceReport) -> str:
        """Export report as canonical JSON (sorted keys, compact separators)."""
        return json.dumps(report.to_dict(), sort_keys=True, indent=2)
