"""Tests for incident_lineage — correlation chain, required fields."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from incident_lineage import (
    IncidentNode, IncidentLineageChain, REQUIRED_LINEAGE_FIELDS,
)


def _node(iid, corr="corr-100", ts="2025-01-01T00:00:00Z", parent=None):
    return IncidentNode(
        incident_id=iid, correlation_id=corr, timestamp=ts,
        source_service="api-gateway", failure_class="TIMEOUT",
        severity="warning", parent_incident_id=parent,
    )


class TestChainBuilding:
    def test_add_and_get(self):
        chain = IncidentLineageChain()
        n = _node("inc-001")
        chain.add_node(n)
        assert chain.get_node("inc-001") is n

    def test_duplicate_raises(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001"))
        with pytest.raises(ValueError):
            chain.add_node(_node("inc-001"))

    def test_ancestor_chain(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001"))
        chain.add_node(_node("inc-002", parent="inc-001"))
        chain.add_node(_node("inc-003", parent="inc-002"))
        ancestors = chain.get_chain("inc-003")
        assert [n.incident_id for n in ancestors] == ["inc-001", "inc-002", "inc-003"]

    def test_root_nodes(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001"))
        chain.add_node(_node("inc-002", parent="inc-001"))
        roots = chain.root_nodes()
        assert len(roots) == 1
        assert roots[0].incident_id == "inc-001"


class TestValidation:
    def test_required_fields_present(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001"))
        assert chain.check_required_fields() == []

    def test_missing_correlation_id(self):
        n = IncidentNode(
            incident_id="inc-bad", correlation_id="",
            timestamp="2025-01-01T00:00:00Z", source_service="svc",
            failure_class="TIMEOUT", severity="warning",
        )
        assert not n.has_required_fields()

    def test_correlation_continuity_pass(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001", corr="corr-100"))
        chain.add_node(_node("inc-002", corr="corr-100", parent="inc-001"))
        assert chain.check_correlation_continuity() == []

    def test_broken_correlation_detected(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001", corr="corr-100"))
        chain.add_node(_node("inc-002", corr="corr-999", parent="inc-001"))
        broken = chain.check_correlation_continuity()
        assert "inc-002" in broken

    def test_dangling_parent_detected(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-002", parent="inc-nonexistent"))
        dangling = chain.check_dangling_parents()
        assert "inc-002" in dangling

    def test_full_audit_pass(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001"))
        chain.add_node(_node("inc-002", parent="inc-001"))
        audit = chain.full_audit()
        assert audit["overall_pass"]
        assert audit["total_nodes"] == 2

    def test_full_audit_fail_on_broken_correlation(self):
        chain = IncidentLineageChain()
        chain.add_node(_node("inc-001", corr="corr-100"))
        chain.add_node(_node("inc-002", corr="corr-different", parent="inc-001"))
        audit = chain.full_audit()
        assert not audit["overall_pass"]
