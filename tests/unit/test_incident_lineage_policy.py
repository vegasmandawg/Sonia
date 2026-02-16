"""Tests for incident_lineage_policy.py — v4.2 E2."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from incident_lineage_policy import (
    IncidentRecord, IncidentLineagePolicy, Severity, ResolutionStatus,
    REQUIRED_INCIDENT_FIELDS,
)


class TestIncidentRecord:
    def test_valid_record(self):
        r = IncidentRecord(
            "i1", "c1", "2026-01-01T00:00:00Z", Severity.HIGH,
            "timeout", "api-gateway", "Test incident", ResolutionStatus.OPEN,
        )
        assert r.incident_id == "i1"
        assert r.fingerprint
        assert r.has_all_required_fields()

    def test_empty_incident_id_rejected(self):
        with pytest.raises(ValueError, match="incident_id"):
            IncidentRecord(
                "", "c1", "2026-01-01T00:00:00Z", Severity.HIGH,
                "timeout", "api-gateway", "desc", ResolutionStatus.OPEN,
            )

    def test_missing_correlation_id_rejected(self):
        with pytest.raises(ValueError, match="correlation_id"):
            IncidentRecord(
                "i1", "", "2026-01-01T00:00:00Z", Severity.HIGH,
                "timeout", "api-gateway", "desc", ResolutionStatus.OPEN,
            )

    def test_fingerprint_deterministic(self):
        r1 = IncidentRecord(
            "i1", "c1", "2026-01-01T00:00:00Z", Severity.LOW,
            "timeout", "svc", "desc", ResolutionStatus.RESOLVED,
        )
        r2 = IncidentRecord(
            "i1", "c1", "2026-01-01T00:00:00Z", Severity.LOW,
            "timeout", "svc", "desc", ResolutionStatus.RESOLVED,
        )
        assert r1.fingerprint == r2.fingerprint


class TestIncidentLineagePolicy:
    def _make_record(self, iid="i1", cid="c1", parent=""):
        return IncidentRecord(
            iid, cid, "2026-01-01T00:00:00Z", Severity.HIGH,
            "timeout", "api-gateway", "Test incident", ResolutionStatus.OPEN,
            parent_correlation_id=parent,
        )

    def test_register_and_check_completeness(self):
        pol = IncidentLineagePolicy()
        pol.register(self._make_record())
        result = pol.check_completeness("i1")
        assert result["complete"] is True

    def test_duplicate_incident_rejected(self):
        pol = IncidentLineagePolicy()
        pol.register(self._make_record())
        with pytest.raises(ValueError, match="Duplicate"):
            pol.register(self._make_record())

    def test_correlation_continuity_valid(self):
        pol = IncidentLineagePolicy()
        pol.register(self._make_record("i1", "c1"))
        result = pol.check_correlation_continuity("c1")
        assert result["continuous"] is True

    def test_correlation_not_found(self):
        pol = IncidentLineagePolicy()
        result = pol.check_correlation_continuity("missing_cid")
        assert result["continuous"] is False

    def test_broken_parent_link_detected(self):
        pol = IncidentLineagePolicy()
        # Register child with parent that doesn't exist
        pol.register(self._make_record("i1", "c1", parent="orphan_parent"))
        result = pol.check_correlation_continuity("c1")
        assert result["continuous"] is False
        assert len(result["broken_links"]) == 1

    def test_chain_completeness(self):
        pol = IncidentLineagePolicy()
        pol.register(self._make_record("i1", "c1"))
        pol.register(self._make_record("i2", "c2", parent="c1"))
        result = pol.check_chain_completeness("c1")
        assert result["all_complete"] is True
        assert result["visited_correlations"] == 2

    def test_get_lineage(self):
        pol = IncidentLineagePolicy()
        pol.register(self._make_record("i1", "c1"))
        pol.register(self._make_record("i2", "c1"))
        lineage = pol.get_lineage("c1")
        assert len(lineage) == 2

    def test_incident_not_found_completeness(self):
        pol = IncidentLineagePolicy()
        result = pol.check_completeness("missing")
        assert result["complete"] is False
