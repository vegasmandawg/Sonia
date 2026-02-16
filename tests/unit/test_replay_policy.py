"""Tests for replay_policy — DLQ dry/live semantics, idempotency."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from replay_policy import (
    DLQEntry, ReplayMode, ReplayVerdict, ReplayPolicyEngine,
    ALL_FAILURE_CLASSES, RETRYABLE_FAILURE_CLASSES, NON_RETRYABLE_FAILURE_CLASSES,
    dry_run_differs_from_live, replay_is_idempotent_in_dry_run,
)


def _entry(eid="dlq-001", fclass="TIMEOUT", retries=1):
    return DLQEntry(eid, "shell.run", "hash1", fclass, retries, f"corr-{eid}", "2025-01-01T00:00:00Z")


class TestRetryableVsNon:
    def test_retryable_accepted(self):
        engine = ReplayPolicyEngine()
        r = engine.evaluate(_entry(fclass="TIMEOUT"), ReplayMode.LIVE)
        assert r.verdict == ReplayVerdict.ACCEPT

    def test_non_retryable_rejected(self):
        engine = ReplayPolicyEngine()
        r = engine.evaluate(_entry(fclass="POLICY_DENIED"), ReplayMode.LIVE)
        assert r.verdict == ReplayVerdict.REJECT

    def test_unknown_class_rejected(self):
        engine = ReplayPolicyEngine()
        r = engine.evaluate(_entry(fclass="IMAGINARY_CLASS"), ReplayMode.LIVE)
        assert r.verdict == ReplayVerdict.REJECT

    def test_retry_budget_exceeded(self):
        engine = ReplayPolicyEngine(max_retry_count=3)
        r = engine.evaluate(_entry(retries=5), ReplayMode.LIVE)
        assert r.verdict == ReplayVerdict.REJECT


class TestDryRunVsLive:
    def test_dry_run_no_side_effects(self):
        engine = ReplayPolicyEngine()
        r = engine.evaluate(_entry(), ReplayMode.DRY_RUN)
        assert r.verdict == ReplayVerdict.ACCEPT
        assert r.side_effects == []

    def test_live_has_side_effects(self):
        engine = ReplayPolicyEngine()
        r = engine.evaluate(_entry(), ReplayMode.LIVE)
        assert r.verdict == ReplayVerdict.ACCEPT
        assert len(r.side_effects) > 0
        assert "action_executed" in r.side_effects

    def test_dry_run_differs_from_live(self):
        entry = _entry()
        engine = ReplayPolicyEngine()
        assert dry_run_differs_from_live(entry, engine)

    def test_replay_idempotent_in_dry_run(self):
        entry = _entry()
        engine = ReplayPolicyEngine()
        assert replay_is_idempotent_in_dry_run(entry, engine)


class TestTaxonomy:
    def test_all_failure_classes_complete(self):
        expected = {"CONNECTION_BOOTSTRAP", "TIMEOUT", "EXECUTION_ERROR", "BACKPRESSURE",
                    "CIRCUIT_OPEN", "POLICY_DENIED", "VALIDATION_FAILED", "UNKNOWN"}
        assert ALL_FAILURE_CLASSES == expected

    def test_retryable_non_retryable_disjoint(self):
        assert RETRYABLE_FAILURE_CLASSES.isdisjoint(NON_RETRYABLE_FAILURE_CLASSES)

    def test_union_is_all(self):
        assert RETRYABLE_FAILURE_CLASSES | NON_RETRYABLE_FAILURE_CLASSES == ALL_FAILURE_CLASSES

    def test_fingerprint_stable(self):
        e = _entry()
        assert e.fingerprint() == e.fingerprint()
