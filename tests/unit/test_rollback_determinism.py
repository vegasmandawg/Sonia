"""Tests for rollback_determinism — scripts, contracts, dry-run stability."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from rollback_determinism import (
    RollbackScript, RollbackScriptRegistry, RollbackVerdict,
    simulate_dry_run, dry_run_is_deterministic, validate_rollback_contract,
)


def _script(sid="rb-001", dry=True, preconds=("svc_stopped",)):
    return RollbackScript(sid, "rollback", "scripts/rb.ps1", "4.0.0", dry, preconds)


class TestRegistry:
    def test_register_and_list(self):
        reg = RollbackScriptRegistry()
        reg.register(_script("rb-001"))
        reg.register(_script("rb-002"))
        assert len(reg.list_all()) == 2

    def test_no_dry_run_detected(self):
        reg = RollbackScriptRegistry()
        reg.register(_script("rb-001", dry=False))
        assert not reg.all_support_dry_run()
        assert "rb-001" in reg.scripts_without_dry_run()


class TestDryRun:
    def test_dry_run_deterministic(self):
        s = _script()
        assert dry_run_is_deterministic(s)

    def test_dry_run_output_has_hash(self):
        s = _script()
        out = simulate_dry_run(s)
        assert len(out.output_hash) == 64
        assert len(out.actions_planned) > 0

    def test_two_runs_same_hash(self):
        s = _script()
        o1 = simulate_dry_run(s)
        o2 = simulate_dry_run(s)
        assert o1.output_hash == o2.output_hash

    def test_different_versions_different_hash(self):
        s1 = _script(sid="rb-001")
        s2 = RollbackScript("rb-002", "rollback", "scripts/rb.ps1", "3.9.0", True, ("svc_stopped",))
        o1 = simulate_dry_run(s1)
        o2 = simulate_dry_run(s2)
        assert o1.output_hash != o2.output_hash


class TestContract:
    def test_valid_contract(self):
        s = _script()
        checks = validate_rollback_contract(s)
        assert all(c.verdict == RollbackVerdict.PASS for c in checks)

    def test_no_dry_run_fails_contract(self):
        s = _script(dry=False)
        checks = validate_rollback_contract(s)
        assert any(c.verdict == RollbackVerdict.FAIL for c in checks)

    def test_no_preconditions_fails(self):
        s = _script(preconds=())
        checks = validate_rollback_contract(s)
        assert any(c.name == "has_preconditions" and c.verdict == RollbackVerdict.FAIL for c in checks)


# --- E3 negative-path tests ---

class TestNegativePaths:
    def test_registry_empty_all_support_dry_run(self):
        reg = RollbackScriptRegistry()
        assert reg.all_support_dry_run()

    def test_registry_get_missing_returns_none(self):
        reg = RollbackScriptRegistry()
        assert reg.get("nonexistent") is None

    def test_fingerprint_deterministic(self):
        s = _script()
        assert s.fingerprint() == s.fingerprint()
        assert len(s.fingerprint()) == 64

    def test_different_scripts_different_fingerprints(self):
        s1 = _script(sid="rb-001")
        s2 = _script(sid="rb-002")
        assert s1.fingerprint() != s2.fingerprint()

    def test_dry_run_output_hash_static_method(self):
        from rollback_determinism import DryRunOutput
        h1 = DryRunOutput.compute_hash(["a", "b"], ["c"])
        h2 = DryRunOutput.compute_hash(["a", "b"], ["c"])
        assert h1 == h2
        h3 = DryRunOutput.compute_hash(["a"], ["c"])
        assert h1 != h3

    def test_contract_all_fail_no_dry_run_no_preconds(self):
        s = RollbackScript("rb-bad", "rollback", "bad.ps1", "1.0.0", False, ())
        checks = validate_rollback_contract(s)
        fails = [c for c in checks if c.verdict == RollbackVerdict.FAIL]
        assert len(fails) >= 2

    def test_multiple_scripts_mixed_dry_run(self):
        reg = RollbackScriptRegistry()
        reg.register(_script("rb-001", dry=True))
        reg.register(_script("rb-002", dry=False))
        reg.register(_script("rb-003", dry=True))
        assert not reg.all_support_dry_run()
        assert reg.scripts_without_dry_run() == ["rb-002"]
