"""Tests for replay_determinism_policy.py — v4.2 E2."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from replay_determinism_policy import (
    DLQEntry, ReplayDeterminismPolicy, ReplayMode, ReplayOutcome,
)


class TestDLQEntry:
    def test_valid_entry(self):
        e = DLQEntry("e1", "create_memory", "hash_a", "timeout", 1, "ns1")
        assert e.entry_id == "e1"
        assert e.fingerprint

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError, match="entry_id"):
            DLQEntry("", "action", "hash", "timeout", 0, "ns1")

    def test_negative_attempt_rejected(self):
        with pytest.raises(ValueError, match="non-negative"):
            DLQEntry("e1", "action", "hash", "timeout", -1, "ns1")


class TestReplayDeterminismPolicy:
    def _make_entry(self, eid="e1", payload_hash="hash_a"):
        return DLQEntry(eid, "create_memory", payload_hash, "timeout", 1, "ns1")

    def test_dry_run_no_side_effects(self):
        pol = ReplayDeterminismPolicy()
        entry = self._make_entry()
        result = pol.evaluate_replay(entry, ReplayMode.DRY_RUN)
        assert result.outcome == ReplayOutcome.SUCCESS
        assert result.side_effects is False
        contract = pol.check_dry_run_contract(result)
        assert contract["valid"] is True

    def test_live_replay_has_side_effects(self):
        pol = ReplayDeterminismPolicy()
        entry = self._make_entry()
        result = pol.evaluate_replay(entry, ReplayMode.LIVE)
        assert result.outcome == ReplayOutcome.SUCCESS
        assert result.side_effects is True
        contract = pol.check_live_contract(result)
        assert contract["valid"] is True

    def test_replay_idempotency(self):
        pol = ReplayDeterminismPolicy()
        entry = self._make_entry()
        r1 = pol.evaluate_replay(entry, ReplayMode.LIVE)
        assert r1.outcome == ReplayOutcome.SUCCESS
        r2 = pol.evaluate_replay(entry, ReplayMode.LIVE)
        assert r2.outcome == ReplayOutcome.SKIPPED_DUPLICATE
        assert r2.side_effects is False

    def test_replay_non_idempotent_path_missing_hash(self):
        pol = ReplayDeterminismPolicy()
        entry = DLQEntry("e1", "action", "", "timeout", 1, "ns1")
        result = pol.evaluate_replay(entry, ReplayMode.LIVE)
        assert result.outcome == ReplayOutcome.FAILED_VALIDATION
        assert result.side_effects is False

    def test_dry_run_does_not_track_idempotency(self):
        pol = ReplayDeterminismPolicy()
        entry = self._make_entry()
        pol.evaluate_replay(entry, ReplayMode.DRY_RUN)
        assert not pol.check_idempotency("e1")
        pol.evaluate_replay(entry, ReplayMode.LIVE)
        assert pol.check_idempotency("e1")

    def test_multiple_entries_independent(self):
        pol = ReplayDeterminismPolicy()
        e1 = self._make_entry("e1")
        e2 = self._make_entry("e2")
        pol.evaluate_replay(e1, ReplayMode.LIVE)
        r2 = pol.evaluate_replay(e2, ReplayMode.LIVE)
        assert r2.outcome == ReplayOutcome.SUCCESS

    def test_replay_log_tracks_all(self):
        pol = ReplayDeterminismPolicy()
        entry = self._make_entry()
        pol.evaluate_replay(entry, ReplayMode.DRY_RUN)
        pol.evaluate_replay(entry, ReplayMode.LIVE)
        assert len(pol.replay_log) == 2

    def test_dry_run_contract_rejects_live(self):
        pol = ReplayDeterminismPolicy()
        entry = self._make_entry()
        result = pol.evaluate_replay(entry, ReplayMode.LIVE)
        contract = pol.check_dry_run_contract(result)
        assert contract["valid"] is False
