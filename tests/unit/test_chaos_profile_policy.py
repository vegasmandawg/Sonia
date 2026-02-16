"""Tests for chaos_profile_policy.py — v4.2 E2."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from chaos_profile_policy import (
    ChaosScenario, ChaosProfile, ChaosProfileRegistry,
    ScenarioType, MAX_TIMEOUT_MS, MAX_RETRIES, MAX_BLAST_RADIUS,
)


class TestChaosScenario:
    def test_valid_scenario(self):
        s = ChaosScenario("s1", ScenarioType.ADAPTER_TIMEOUT, 5000, 2, 1, "timeout test")
        assert s.scenario_id == "s1"
        assert s.fingerprint

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="scenario_id"):
            ChaosScenario("", ScenarioType.ADAPTER_TIMEOUT, 5000, 2, 1, "test")

    def test_timeout_exceeds_cap(self):
        with pytest.raises(ValueError, match="exceeds cap"):
            ChaosScenario("s1", ScenarioType.ADAPTER_TIMEOUT, MAX_TIMEOUT_MS + 1, 2, 1, "test")

    def test_retries_exceed_cap(self):
        with pytest.raises(ValueError, match="exceeds cap"):
            ChaosScenario("s1", ScenarioType.ADAPTER_TIMEOUT, 1000, MAX_RETRIES + 1, 1, "test")

    def test_blast_radius_exceeds_cap(self):
        with pytest.raises(ValueError, match="exceeds cap"):
            ChaosScenario("s1", ScenarioType.CASCADE_FAILURE, 1000, 1, MAX_BLAST_RADIUS + 1, "test")

    def test_fingerprint_deterministic(self):
        s1 = ChaosScenario("s1", ScenarioType.BREAKER_TRIP, 3000, 1, 2, "trip test")
        s2 = ChaosScenario("s1", ScenarioType.BREAKER_TRIP, 3000, 1, 2, "trip test")
        assert s1.fingerprint == s2.fingerprint


class TestChaosProfileRegistry:
    def _make_scenario(self, sid="s1"):
        return ChaosScenario(sid, ScenarioType.ADAPTER_TIMEOUT, 5000, 2, 1, "test")

    def test_register_and_get(self):
        reg = ChaosProfileRegistry()
        profile = ChaosProfile("p1", 1, (self._make_scenario(),), "test profile")
        reg.register(profile)
        assert reg.get("p1") is not None
        assert reg.profile_count == 1

    def test_version_conflict_rejected(self):
        reg = ChaosProfileRegistry()
        reg.register(ChaosProfile("p1", 1, (self._make_scenario(),), "v1"))
        with pytest.raises(ValueError, match="must be >"):
            reg.register(ChaosProfile("p1", 1, (self._make_scenario(),), "v1 dup"))

    def test_hash_stability(self):
        reg = ChaosProfileRegistry()
        profile = ChaosProfile("p1", 1, (self._make_scenario(),), "test")
        reg.register(profile)
        result = reg.verify_hash_stability("p1")
        assert result["valid"] is True
        assert result["fingerprint"] == profile.fingerprint

    def test_bounds_check_valid(self):
        reg = ChaosProfileRegistry()
        s = self._make_scenario()
        result = reg.check_bounds(s)
        assert result["bounded"] is True

    def test_empty_scenarios_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            ChaosProfile("p1", 1, (), "empty")
