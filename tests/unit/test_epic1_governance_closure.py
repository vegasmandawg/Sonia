"""Tests for E1 governance closure (cross-module integration) — 7 tests."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from provenance_registry import GovernanceControl, ProvenanceRegistry, DuplicateControlError
from lineage_mapper import (
    LineageMapper, GateCheckBinding, TestFamilyBinding, ArtifactPatternBinding,
)
from evidence_integrity import EvidenceIntegrityChecker, EvidenceRecord
from provenance_reporter import ProvenanceReporter


def _build_full_model():
    """Build a complete governance model for integration tests."""
    registry = ProvenanceRegistry()
    controls = [
        GovernanceControl("CTL-001", "Auth", "Auth posture", "security", "critical", "4.1.0"),
        GovernanceControl("CTL-002", "Session", "Session isolation", "security", "high", "4.1.0"),
        GovernanceControl("CTL-003", "Recovery", "Recovery determinism", "reliability", "critical", "4.1.0"),
    ]
    for c in controls:
        registry.register(c)

    mapper = LineageMapper()
    mapper.register_control_ids(registry.all_ids())
    for c in controls:
        mapper.bind_gate_check(GateCheckBinding(c.control_id, "gate.py", f"check_{c.control_id}"))
        mapper.bind_test_family(TestFamilyBinding(c.control_id, "test.py", f"Test_{c.control_id}"))
        mapper.bind_artifact_pattern(ArtifactPatternBinding(c.control_id, f"{c.control_id}-*.json", "gate_report"))

    checker = EvidenceIntegrityChecker()
    for c in controls:
        checker.register(EvidenceRecord(
            artifact_id=f"ev-{c.control_id}",
            artifact_path=f"reports/{c.control_id}.json",
            sha256_hash="a" * 64,
            timestamp_utc="2026-02-16T15:00:00+00:00",
            source="provenance-gate",
            artifact_type="gate_report",
        ))

    return registry, mapper, checker, controls


class TestFullProvenanceReport:
    def test_report_overall_pass(self):
        registry, mapper, checker, _ = _build_full_model()
        reporter = ProvenanceReporter(registry, mapper, checker)
        report = reporter.generate(timestamp_utc="2026-02-16T15:00:00+00:00")
        assert report.overall_verdict == "PASS"

    def test_report_hash_deterministic(self):
        registry, mapper, checker, _ = _build_full_model()
        reporter = ProvenanceReporter(registry, mapper, checker)
        ts = "2026-02-16T15:00:00+00:00"
        r1 = reporter.generate(timestamp_utc=ts)
        r2 = reporter.generate(timestamp_utc=ts)
        assert r1.report_hash == r2.report_hash
        assert len(r1.report_hash) == 64

    def test_rerun_parity(self):
        registry, mapper, checker, _ = _build_full_model()
        reporter = ProvenanceReporter(registry, mapper, checker)
        ts = "2026-02-16T15:00:00+00:00"
        r1 = reporter.generate(timestamp_utc=ts)
        r2 = reporter.generate(timestamp_utc=ts)
        assert reporter.verify_rerun_parity(r1, r2)


class TestIncompleteModel:
    def test_missing_test_binding_fails_completeness(self):
        registry, mapper, checker, _ = _build_full_model()
        # Add control without test binding
        c4 = GovernanceControl("CTL-004", "New", "New ctrl", "data", "low", "4.1.0")
        registry.register(c4)
        mapper.register_control_id("CTL-004")
        mapper.bind_gate_check(GateCheckBinding("CTL-004", "gate.py", "check_CTL-004"))
        # No test or artifact binding for CTL-004

        reporter = ProvenanceReporter(registry, mapper, checker)
        report = reporter.generate(timestamp_utc="2026-02-16T15:00:00+00:00")
        assert report.overall_verdict == "FAIL"
        assert report.lineage_completeness["completeness_pct"] < 100.0

    def test_broken_gate_mapping_creates_orphan(self):
        mapper = LineageMapper()
        mapper.register_control_ids(["CTL-001"])
        mapper.bind_gate_check(GateCheckBinding("CTL-FAKE", "gate.py", "check_fake"))
        orphans = mapper.orphan_gate_checks()
        assert len(orphans) == 1

    def test_timestamp_violation_fails_report(self):
        registry, mapper, _, controls = _build_full_model()
        checker = EvidenceIntegrityChecker()
        # Register with non-monotonic timestamps
        checker.register(EvidenceRecord("ev-CTL-001", "r/1.json", "a"*64,
                                        "2026-02-16T18:00:00+00:00", "provenance-gate", "gate_report"))
        checker.register(EvidenceRecord("ev-CTL-002", "r/2.json", "a"*64,
                                        "2026-02-16T10:00:00+00:00", "provenance-gate", "gate_report"))
        checker.define_sequence("seq", ["ev-CTL-001", "ev-CTL-002"])

        reporter = ProvenanceReporter(registry, mapper, checker)
        report = reporter.generate(timestamp_utc="2026-02-16T15:00:00+00:00")
        assert report.overall_verdict == "FAIL"

    def test_export_json_deterministic(self):
        registry, mapper, checker, _ = _build_full_model()
        reporter = ProvenanceReporter(registry, mapper, checker)
        ts = "2026-02-16T15:00:00+00:00"
        r1 = reporter.generate(timestamp_utc=ts)
        j1 = reporter.export_json(r1)
        j2 = reporter.export_json(r1)
        assert j1 == j2
        assert '"overall_verdict": "PASS"' in j1
