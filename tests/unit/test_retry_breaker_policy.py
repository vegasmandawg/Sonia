"""Tests for retry_breaker_policy.py — v4.2 E2."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from retry_breaker_policy import (
    RetryTaxonomyPolicy, FailureClass, RetryDecision,
    BreakerFSM, BreakerState, VALID_TRANSITIONS,
    FallbackEnvelope, validate_fallback_envelope,
)


class TestRetryTaxonomy:
    def test_completeness(self):
        pol = RetryTaxonomyPolicy()
        result = pol.check_completeness()
        assert result["complete"] is True
        assert result["covered"] == 8

    def test_retryable_class_retries(self):
        pol = RetryTaxonomyPolicy()
        result = pol.decide("timeout", 0)
        assert result["decision"] == RetryDecision.RETRY.value
        assert result["retryable"] is True

    def test_non_retryable_class_no_retry(self):
        pol = RetryTaxonomyPolicy()
        result = pol.decide("policy_denied", 0)
        assert result["decision"] == RetryDecision.NO_RETRY.value

    def test_exceeded_attempts_escalates(self):
        pol = RetryTaxonomyPolicy()
        result = pol.decide("timeout", 10)
        assert result["decision"] == RetryDecision.ESCALATE.value

    def test_unknown_class_escalates(self):
        pol = RetryTaxonomyPolicy()
        result = pol.decide("totally_bogus_class", 0)
        assert result["decision"] == RetryDecision.ESCALATE.value

    def test_deterministic_decisions(self):
        p1 = RetryTaxonomyPolicy()
        p2 = RetryTaxonomyPolicy()
        r1 = p1.decide("timeout", 1)
        r2 = p2.decide("timeout", 1)
        assert r1 == r2


class TestBreakerFSM:
    def test_initial_state_closed(self):
        b = BreakerFSM("test", failure_threshold=3)
        assert b.state == BreakerState.CLOSED

    def test_trip_on_threshold(self):
        b = BreakerFSM("test", failure_threshold=3)
        b.record_failure()
        b.record_failure()
        result = b.record_failure()
        assert b.state == BreakerState.OPEN
        assert result["tripped"] is True

    def test_open_to_half_open(self):
        b = BreakerFSM("test", failure_threshold=1)
        b.record_failure()
        assert b.state == BreakerState.OPEN
        b.attempt_reset()
        assert b.state == BreakerState.HALF_OPEN

    def test_half_open_success_closes(self):
        b = BreakerFSM("test", failure_threshold=1, success_threshold=1)
        b.record_failure()
        b.attempt_reset()
        result = b.record_success()
        assert b.state == BreakerState.CLOSED
        assert result["recovered"] is True

    def test_half_open_failure_reopens(self):
        b = BreakerFSM("test", failure_threshold=1)
        b.record_failure()
        b.attempt_reset()
        b.record_failure()
        assert b.state == BreakerState.OPEN

    def test_illegal_transition_rejected(self):
        b = BreakerFSM("test", failure_threshold=3)
        # CLOSED -> HALF_OPEN is illegal
        assert not b.check_transition_validity("closed", "half_open")
        # CLOSED -> OPEN is legal
        assert b.check_transition_validity("closed", "open")

    def test_deterministic_sequence(self):
        b1 = BreakerFSM("t1", failure_threshold=2)
        b2 = BreakerFSM("t2", failure_threshold=2)
        for b in [b1, b2]:
            b.record_failure()
            b.record_failure()
            b.attempt_reset()
            b.record_success()
        assert b1.state == b2.state

    def test_transition_log(self):
        b = BreakerFSM("test", failure_threshold=1)
        b.record_failure()
        assert len(b.transition_log) == 1
        assert b.transition_log[0]["from"] == "closed"
        assert b.transition_log[0]["to"] == "open"


class TestFallbackEnvelope:
    def test_valid_envelope(self):
        env = FallbackEnvelope("create_memory", "return_cached", "timeout", True)
        assert env.fingerprint
        result = validate_fallback_envelope(env)
        assert result["valid"] is True

    def test_same_action_rejected(self):
        env = FallbackEnvelope("action_a", "action_a", "timeout", True)
        result = validate_fallback_envelope(env)
        assert result["valid"] is False

    def test_not_degraded_rejected(self):
        env = FallbackEnvelope("action_a", "action_b", "timeout", False)
        result = validate_fallback_envelope(env)
        assert result["valid"] is False

    def test_unknown_failure_class_rejected(self):
        env = FallbackEnvelope("action_a", "action_b", "totally_bogus", True)
        result = validate_fallback_envelope(env)
        assert result["valid"] is False
