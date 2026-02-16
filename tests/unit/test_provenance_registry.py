"""Tests for provenance_registry.py — 9 tests."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from provenance_registry import (
    GovernanceControl, ProvenanceRegistry,
    DuplicateControlError, ControlNotFoundError,
)


def _make_control(cid="CTL-001", name="Test", cat="security", sev="high", ver="4.1.0"):
    return GovernanceControl(cid, name, f"Desc for {cid}", cat, sev, ver)


class TestRegistration:
    def test_register_and_get(self):
        reg = ProvenanceRegistry()
        c = _make_control()
        reg.register(c)
        assert reg.get("CTL-001") is c
        assert reg.count() == 1

    def test_duplicate_raises(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-001"))
        with pytest.raises(DuplicateControlError) as exc:
            reg.register(_make_control("CTL-001", name="Different"))
        assert exc.value.control_id == "CTL-001"

    def test_not_found_raises(self):
        reg = ProvenanceRegistry()
        with pytest.raises(ControlNotFoundError):
            reg.get("CTL-999")

    def test_has_check(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-001"))
        assert reg.has("CTL-001")
        assert not reg.has("CTL-999")


class TestQuery:
    def test_list_all_sorted(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-003"))
        reg.register(_make_control("CTL-001"))
        reg.register(_make_control("CTL-002"))
        ids = [c.control_id for c in reg.list_all()]
        assert ids == ["CTL-001", "CTL-002", "CTL-003"]

    def test_list_by_category(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-001", cat="security"))
        reg.register(_make_control("CTL-002", cat="data"))
        reg.register(_make_control("CTL-003", cat="security"))
        sec = reg.list_by_category("security")
        assert len(sec) == 2
        assert [c.control_id for c in sec] == ["CTL-001", "CTL-003"]

    def test_list_by_severity(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-001", sev="critical"))
        reg.register(_make_control("CTL-002", sev="low"))
        crit = reg.list_by_severity("critical")
        assert len(crit) == 1


class TestManifest:
    def test_manifest_deterministic(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-001"))
        reg.register(_make_control("CTL-002"))
        m1 = reg.export_manifest()
        m2 = reg.export_manifest()
        assert m1["manifest_hash"] == m2["manifest_hash"]
        assert m1["control_count"] == 2
        assert len(m1["manifest_hash"]) == 64

    def test_uniqueness_check_clean(self):
        reg = ProvenanceRegistry()
        reg.register(_make_control("CTL-001"))
        reg.register(_make_control("CTL-002"))
        assert reg.check_uniqueness() == []
