"""
Epic 1 Section Closure Tests (J/S/M/O/Q/W assertions).
8+ tests verifying each target section has gate, test, and artifact coverage.
"""
import sys
import importlib.util

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\memory-engine")

from coverage_completeness import (
    CoverageCompletenessAnalyzer,
    GATE_SECTION_MAP,
    TEST_SECTION_MAP,
    ARTIFACT_SECTION_MAP,
)
from durability_policy import (
    DurabilityPolicyRunner,
    MigrationMonotonicityChecker,
    BackupChainVerifier,
    BackupEntry,
    ConnectionDurabilityChecker,
    DurabilityVerdict,
)


class TestSectionJ_DataManagement:
    """Section J (-2 -> 0): Data management hardening."""

    def test_section_j_has_gate_coverage(self):
        covered_by = [g for g, secs in GATE_SECTION_MAP.items() if "J" in secs]
        assert len(covered_by) >= 2, f"Section J gates: {covered_by}"

    def test_section_j_has_test_coverage(self):
        covered_by = [t for t, secs in TEST_SECTION_MAP.items() if "J" in secs]
        assert len(covered_by) >= 2, f"Section J tests: {covered_by}"

    def test_durability_module_covers_data_management(self):
        runner = DurabilityPolicyRunner()
        runner.migration_checker.register(1, "init")
        runner.migration_checker.register(2, "v2")
        report = runner.run_all()
        check_names = [c.name for c in report.checks]
        assert "migration_monotonicity" in check_names
        assert "version_continuity" in check_names


class TestSectionS_Automation:
    """Section S (-2 -> 0): CI/CD automation coverage."""

    def test_section_s_has_gate_coverage(self):
        covered_by = [g for g, secs in GATE_SECTION_MAP.items() if "S" in secs]
        assert len(covered_by) >= 2, f"Section S gates: {covered_by}"

    def test_section_s_has_artifact_coverage(self):
        covered_by = [a for a, secs in ARTIFACT_SECTION_MAP.items() if "S" in secs]
        assert len(covered_by) >= 2, f"Section S artifacts: {covered_by}"


class TestSectionM_StoreDurability:
    """Section M (-1 -> 0): Store durability evidence."""

    def test_section_m_has_gate_coverage(self):
        covered_by = [g for g, secs in GATE_SECTION_MAP.items() if "M" in secs]
        assert len(covered_by) >= 3, f"Section M gates: {covered_by}"

    def test_durability_backup_check(self):
        bv = BackupChainVerifier()
        bv.add_entry(BackupEntry("root", None, "hash", 100))
        assert bv.verify_chain().verdict == DurabilityVerdict.PASS


class TestSectionO_OperationalReadiness:
    """Section O (-1 -> 0): Operational readiness."""

    def test_section_o_has_gate_coverage(self):
        covered_by = [g for g, secs in GATE_SECTION_MAP.items() if "O" in secs]
        assert len(covered_by) >= 1, f"Section O gates: {covered_by}"

    def test_section_o_has_test_coverage(self):
        covered_by = [t for t, secs in TEST_SECTION_MAP.items() if "O" in secs]
        assert len(covered_by) >= 1, f"Section O tests: {covered_by}"


class TestSectionQ_Privacy:
    """Section Q (-1 -> 0): Privacy & compliance."""

    def test_section_q_has_gate_coverage(self):
        covered_by = [g for g, secs in GATE_SECTION_MAP.items() if "Q" in secs]
        assert len(covered_by) >= 3, f"Section Q gates: {covered_by}"

    def test_section_q_has_test_coverage(self):
        covered_by = [t for t, secs in TEST_SECTION_MAP.items() if "Q" in secs]
        assert len(covered_by) >= 1, f"Section Q tests: {covered_by}"


class TestSectionW_Documentation:
    """Section W (-1 -> 0): Documentation completeness."""

    def test_section_w_has_gate_coverage(self):
        covered_by = [g for g, secs in GATE_SECTION_MAP.items() if "W" in secs]
        assert len(covered_by) >= 1, f"Section W gates: {covered_by}"

    def test_section_w_has_test_coverage(self):
        covered_by = [t for t, secs in TEST_SECTION_MAP.items() if "W" in secs]
        assert len(covered_by) >= 1, f"Section W tests: {covered_by}"

    def test_section_w_has_artifact_coverage(self):
        covered_by = [a for a, secs in ARTIFACT_SECTION_MAP.items() if "W" in secs]
        assert len(covered_by) >= 1, f"Section W artifacts: {covered_by}"


class TestAllTargetsClosure:
    """Cross-section closure validation."""

    def test_all_epic1_targets_complete(self):
        a = CoverageCompletenessAnalyzer()
        r = a.check_target_sections(["J", "S", "M", "O", "Q", "W"])
        assert r["all_targets_complete"], (
            f"Incomplete: {r['incomplete_sections']}, "
            f"Missing: {r['missing_details']}"
        )

    def test_completeness_above_80_percent(self):
        a = CoverageCompletenessAnalyzer()
        r = a.check_completeness()
        assert r["completeness_pct"] >= 80.0
