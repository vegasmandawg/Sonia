"""
Stage 6 — Reliability Hardening Tests
Tests for retry taxonomy, DLQ replay dry-run, and breaker metrics export.
"""

import sys
import httpx
import pytest
import uuid

sys.path.insert(0, r"S:\services\api-gateway")

GW = "http://127.0.0.1:7000"


@pytest.fixture
def client():
    return httpx.Client(base_url=GW, timeout=30)


# ── Retry taxonomy ──────────────────────────────────────────────────────────

class TestRetryTaxonomy:
    """Test failure classification on action execution results."""

    def test_safe_action_no_failure_class(self, client):
        """Successful actions should have no failure_class."""
        body = {
            "intent": "window.list",
            "params": {},
            "idempotency_key": f"rt-safe-{uuid.uuid4().hex[:8]}",
        }
        r = client.post("/v1/actions/plan", json=body)
        data = r.json()
        assert data["ok"] is True
        assert data["state"] == "succeeded"
        # Successful execution — failure_class should be absent or None
        if data.get("execution"):
            assert data["execution"].get("failure_class") is None

    def test_unknown_intent_has_validation_failed_class(self, client):
        """Unknown intents produce VALIDATION_FAILED and no failure_class on execution."""
        body = {
            "intent": "nonexistent.bogus",
            "params": {},
            "idempotency_key": f"rt-unk-{uuid.uuid4().hex[:8]}",
        }
        r = client.post("/v1/actions/plan", json=body)
        data = r.json()
        assert data["ok"] is False
        # Should have error code VALIDATION_FAILED
        assert data["error"]["code"] == "VALIDATION_FAILED"
        # No execution result (failed at validation)
        assert data.get("execution") is None

    def test_failure_class_present_in_dead_letter(self, client):
        """Dead letters should include failure_class field."""
        r = client.get("/v1/dead-letters", params={"include_replayed": True})
        data = r.json()
        assert data["ok"] is True
        # All dead letters should have failure_class key
        for dl in data.get("dead_letters", []):
            assert "failure_class" in dl


class TestRetryTaxonomyUnit:
    """Unit tests for the classify_failure function."""

    def test_classify_circuit_open(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_code="CIRCUIT_OPEN") == FailureClass.CIRCUIT_OPEN

    def test_classify_timeout(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_code="TIMEOUT") == FailureClass.TIMEOUT

    def test_classify_policy_denied(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_code="POLICY_DENIED") == FailureClass.POLICY_DENIED

    def test_classify_connection_refused(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_message="connection refused") == FailureClass.CONNECTION_BOOTSTRAP

    def test_classify_execution_failed(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_code="EXECUTION_FAILED") == FailureClass.EXECUTION_ERROR

    def test_classify_backpressure_429(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_code="429") == FailureClass.BACKPRESSURE

    def test_classify_unknown(self):
        from retry_taxonomy import classify_failure, FailureClass
        assert classify_failure(error_code="SOMETHING_WEIRD") == FailureClass.UNKNOWN

    def test_is_retryable_circuit_open(self):
        from retry_taxonomy import is_retryable, FailureClass
        assert is_retryable(FailureClass.CIRCUIT_OPEN) is False

    def test_is_retryable_timeout(self):
        from retry_taxonomy import is_retryable, FailureClass
        assert is_retryable(FailureClass.TIMEOUT) is True

    def test_get_backoff_base(self):
        from retry_taxonomy import get_backoff_base, FailureClass
        assert get_backoff_base(FailureClass.BACKPRESSURE) == 3.0
        assert get_backoff_base(FailureClass.TIMEOUT) == 1.5


# ── DLQ replay dry-run ──────────────────────────────────────────────────────

class TestDLQReplayDryRun:
    """Test dead letter replay with dry_run mode."""

    def test_replay_nonexistent_returns_not_found(self, client):
        """Replaying a nonexistent dead letter returns NOT_FOUND."""
        r = client.post("/v1/dead-letters/dl_nonexistent/replay",
                        params={"dry_run": True})
        data = r.json()
        assert data["ok"] is False
        assert data["error"]["code"] == "NOT_FOUND"

    def test_replay_dry_run_validates_only(self, client):
        """dry_run=true should validate but not execute the replay."""
        # First, check if there are any dead letters to replay
        r = client.get("/v1/dead-letters", params={"include_replayed": False})
        data = r.json()
        if data["total"] > 0:
            letter = data["dead_letters"][0]
            lid = letter["letter_id"]
            # Dry-run replay
            rr = client.post(f"/v1/dead-letters/{lid}/replay",
                             params={"dry_run": True})
            replay_data = rr.json()
            # Should not fail on request
            assert rr.status_code == 200
            # Should include replay_diff
            assert "replay_diff" in replay_data.get("error", {})
            diff = replay_data["error"]["replay_diff"]
            assert diff["replay_dry_run"] is True
            assert diff["letter_id"] == lid
            # Should NOT be marked as replayed
            check = client.get(f"/v1/dead-letters/{lid}")
            if check.status_code == 200:
                assert check.json()["dead_letter"]["replayed"] is False

    def test_replay_endpoint_accepts_dry_run_param(self, client):
        """Verify the replay endpoint accepts dry_run query param."""
        # Just test the endpoint handles the parameter without error
        r = client.post("/v1/dead-letters/dl_fake/replay",
                        params={"dry_run": True})
        assert r.status_code == 200
        data = r.json()
        # Should be NOT_FOUND, not a 422 from invalid param
        assert data["error"]["code"] == "NOT_FOUND"


# ── Breaker metrics export ──────────────────────────────────────────────────

class TestBreakerMetrics:
    """Test circuit breaker metrics export endpoint."""

    def test_breaker_metrics_endpoint_exists(self, client):
        """GET /v1/breakers/metrics returns 200."""
        r = client.get("/v1/breakers/metrics")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "metrics" in data

    def test_breaker_metrics_contains_openclaw(self, client):
        """Metrics should include the openclaw breaker."""
        r = client.get("/v1/breakers/metrics")
        data = r.json()
        assert "openclaw" in data["metrics"]

    def test_breaker_metrics_structure(self, client):
        """Each breaker metric export should have required fields."""
        r = client.get("/v1/breakers/metrics")
        data = r.json()
        for name, metric in data["metrics"].items():
            assert "name" in metric
            assert "state" in metric
            assert "event_counts" in metric
            assert "total_metric_events" in metric
            assert "recent_events" in metric
            assert isinstance(metric["recent_events"], list)

    def test_breaker_metrics_accumulate_after_actions(self, client):
        """After running actions, breaker should have metric events."""
        # Run a safe action (goes through openclaw breaker)
        body = {
            "intent": "window.list",
            "params": {},
            "idempotency_key": f"bm-{uuid.uuid4().hex[:8]}",
        }
        client.post("/v1/actions/plan", json=body)

        # Check metrics
        r = client.get("/v1/breakers/metrics")
        data = r.json()
        oc = data["metrics"]["openclaw"]
        assert oc["total_metric_events"] > 0
        # Should have at least one success event
        assert oc["event_counts"].get("success", 0) > 0

    def test_breaker_metrics_last_n_param(self, client):
        """last_n parameter limits recent events returned."""
        r = client.get("/v1/breakers/metrics", params={"last_n": 2})
        data = r.json()
        for name, metric in data["metrics"].items():
            assert len(metric["recent_events"]) <= 2

    def test_breaker_reset_creates_metric_event(self, client):
        """Resetting a breaker should record a 'reset' metric event."""
        # Reset openclaw
        client.post("/v1/breakers/openclaw/reset")

        # Check for reset event in metrics
        r = client.get("/v1/breakers/metrics", params={"last_n": 5})
        data = r.json()
        oc = data["metrics"]["openclaw"]
        recent_types = [e["event"] for e in oc["recent_events"]]
        assert "reset" in recent_types


# ── Backward compatibility ──────────────────────────────────────────────────

class TestStage5Compat:
    """Ensure Stage 5 functionality still works after Stage 6 changes."""

    def test_healthz(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_breakers_endpoint_unchanged(self, client):
        """GET /v1/breakers still returns breaker states."""
        r = client.get("/v1/breakers")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "breakers" in data
        assert "openclaw" in data["breakers"]

    def test_dead_letters_endpoint_unchanged(self, client):
        """GET /v1/dead-letters still works."""
        r = client.get("/v1/dead-letters")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_capabilities_still_13(self, client):
        """All 13 capabilities still implemented."""
        r = client.get("/v1/capabilities")
        data = r.json()
        assert data["stats"]["total"] == 13
        assert data["stats"]["implemented"] == 13

    def test_safe_action_still_succeeds(self, client):
        """Safe actions still execute correctly."""
        body = {
            "intent": "clipboard.read",
            "params": {},
            "idempotency_key": f"s5c-{uuid.uuid4().hex[:8]}",
        }
        r = client.post("/v1/actions/plan", json=body)
        data = r.json()
        assert data["ok"] is True
        assert data["state"] == "succeeded"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
