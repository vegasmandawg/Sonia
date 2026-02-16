"""Tests for chaos_policy module — scenario registry, bounds, determinism."""
import sys, hashlib
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from chaos_policy import (
    ChaosScenario, ChaosPolicyRegistry, DuplicateScenarioError,
    ScenarioNotFoundError, SCHEMA_VERSION,
)


def _scenario(sid="cs-001", name="timeout", adapter="native", fault="timeout",
              timeout_ms=5000, retries=3, scope="single_action", seed=42):
    return ChaosScenario(sid, name, "desc", adapter, fault, timeout_ms, retries, scope, seed)


class TestRegistration:
    def test_register_and_get(self):
        reg = ChaosPolicyRegistry()
        s = _scenario()
        reg.register(s)
        assert reg.get("cs-001") is s
        assert reg.has("cs-001")

    def test_duplicate_raises(self):
        reg = ChaosPolicyRegistry()
        reg.register(_scenario())
        with pytest.raises(DuplicateScenarioError):
            reg.register(_scenario())

    def test_not_found_raises(self):
        reg = ChaosPolicyRegistry()
        with pytest.raises(ScenarioNotFoundError):
            reg.get("nonexistent")

    def test_version_matches_schema(self):
        reg = ChaosPolicyRegistry()
        assert reg.version == SCHEMA_VERSION


class TestBounds:
    def test_bounded_scenario(self):
        s = _scenario(timeout_ms=5000, retries=3, scope="single_action")
        assert s.is_bounded()

    def test_unbounded_timeout(self):
        s = _scenario(timeout_ms=100_000)
        assert not s.is_bounded()

    def test_negative_timeout_raises(self):
        with pytest.raises(ValueError):
            _scenario(timeout_ms=-1)

    def test_negative_retries_raises(self):
        with pytest.raises(ValueError):
            _scenario(retries=-1)

    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError):
            _scenario(scope="global")

    def test_all_bounded_check(self):
        reg = ChaosPolicyRegistry()
        reg.register(_scenario("cs-001"))
        reg.register(_scenario("cs-002", timeout_ms=1000))
        assert reg.all_bounded()
        assert len(reg.unbounded_scenarios()) == 0


class TestManifest:
    def test_manifest_deterministic(self):
        reg = ChaosPolicyRegistry()
        reg.register(_scenario("cs-001"))
        reg.register(_scenario("cs-002", name="error"))
        m1 = reg.export_manifest()
        m2 = reg.export_manifest()
        assert m1["manifest_hash"] == m2["manifest_hash"]
        assert m1["scenario_count"] == 2

    def test_fingerprint_stable(self):
        s = _scenario()
        assert s.fingerprint() == s.fingerprint()
        assert len(s.fingerprint()) == 64  # SHA-256 hex
