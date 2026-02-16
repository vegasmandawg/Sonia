"""Tests for determinism_report — combined audit, rerun parity."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from determinism_report import DeterminismReport, DeterminismReporter


def _make_reporter(pre=True, post=True, dry_safe=True, differs=True, lineage_pass=True):
    chaos_manifest = {"schema_version": "1.0.0", "scenario_count": 4, "manifest_hash": "abc"}
    lineage_audit = {"overall_pass": lineage_pass, "total_nodes": 3, "root_count": 1,
                     "missing_required_fields": [], "broken_correlation_continuity": [],
                     "dangling_parent_references": []}
    return DeterminismReporter(
        chaos_manifest=chaos_manifest,
        restore_pre_pass=pre,
        restore_post_pass=post,
        replay_dry_safe=dry_safe,
        replay_differs=differs,
        lineage_audit=lineage_audit,
    )


class TestDeterminismReport:
    def test_report_overall_pass(self):
        reporter = _make_reporter()
        report = reporter.generate(fixed_timestamp="2025-01-01T00:00:00Z")
        assert report.overall_verdict == "PASS"
        assert report.report_hash != ""

    def test_report_hash_deterministic(self):
        reporter = _make_reporter()
        r1 = reporter.generate(fixed_timestamp="2025-01-01T00:00:00Z")
        r2 = reporter.generate(fixed_timestamp="2025-01-01T00:00:00Z")
        assert r1.report_hash == r2.report_hash

    def test_rerun_parity(self):
        reporter = _make_reporter()
        assert reporter.verify_rerun_parity("2025-01-01T00:00:00Z")

    def test_fail_on_broken_restore(self):
        reporter = _make_reporter(post=False)
        report = reporter.generate(fixed_timestamp="2025-01-01T00:00:00Z")
        assert report.overall_verdict == "FAIL"

    def test_fail_on_broken_lineage(self):
        reporter = _make_reporter(lineage_pass=False)
        report = reporter.generate(fixed_timestamp="2025-01-01T00:00:00Z")
        assert report.overall_verdict == "FAIL"
