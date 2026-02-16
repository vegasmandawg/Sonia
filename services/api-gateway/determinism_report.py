"""
Determinism report: stable summary/hash across reruns.

Combines chaos, restore, replay, and incident lineage audits into a
single deterministic report with reproducible hashing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class DeterminismReport:
    """A combined audit report for recovery determinism."""
    version: str = "1.0.0"
    timestamp: str = ""
    chaos_manifest: Optional[Dict[str, Any]] = None
    restore_precondition_pass: bool = False
    restore_postcondition_pass: bool = False
    replay_dry_run_safe: bool = False
    replay_semantics_differ: bool = False
    incident_lineage_audit: Optional[Dict[str, Any]] = None
    overall_verdict: str = "FAIL"
    report_hash: str = ""

    def compute_hash(self) -> str:
        """Compute deterministic hash of report content."""
        content = {
            "version": self.version,
            "timestamp": self.timestamp,
            "chaos_manifest": self.chaos_manifest,
            "restore_precondition_pass": self.restore_precondition_pass,
            "restore_postcondition_pass": self.restore_postcondition_pass,
            "replay_dry_run_safe": self.replay_dry_run_safe,
            "replay_semantics_differ": self.replay_semantics_differ,
            "incident_lineage_audit": self.incident_lineage_audit,
            "overall_verdict": self.overall_verdict,
        }
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class DeterminismReporter:
    """Generates deterministic recovery audit reports."""

    def __init__(
        self,
        chaos_manifest: Dict[str, Any],
        restore_pre_pass: bool,
        restore_post_pass: bool,
        replay_dry_safe: bool,
        replay_differs: bool,
        lineage_audit: Dict[str, Any],
    ):
        self._chaos_manifest = chaos_manifest
        self._restore_pre_pass = restore_pre_pass
        self._restore_post_pass = restore_post_pass
        self._replay_dry_safe = replay_dry_safe
        self._replay_differs = replay_differs
        self._lineage_audit = lineage_audit

    def generate(self, fixed_timestamp: Optional[str] = None) -> DeterminismReport:
        ts = fixed_timestamp or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        overall = all([
            self._restore_pre_pass,
            self._restore_post_pass,
            self._replay_dry_safe,
            self._replay_differs,
            self._lineage_audit.get("overall_pass", False),
        ])
        report = DeterminismReport(
            timestamp=ts,
            chaos_manifest=self._chaos_manifest,
            restore_precondition_pass=self._restore_pre_pass,
            restore_postcondition_pass=self._restore_post_pass,
            replay_dry_run_safe=self._replay_dry_safe,
            replay_semantics_differ=self._replay_differs,
            incident_lineage_audit=self._lineage_audit,
            overall_verdict="PASS" if overall else "FAIL",
        )
        report.report_hash = report.compute_hash()
        return report

    def verify_rerun_parity(
        self, fixed_timestamp: str
    ) -> bool:
        """Generate two reports with same timestamp and verify hash match."""
        r1 = self.generate(fixed_timestamp=fixed_timestamp)
        r2 = self.generate(fixed_timestamp=fixed_timestamp)
        return r1.report_hash == r2.report_hash and r1.report_hash != ""
