"""
Stage 5 M2 — test_recovery_and_dead_letter.py
Tests for circuit breaker, dead letter queue, health supervisor, and recovery endpoints.
"""

import sys
import asyncio
import httpx
import pytest
import time

sys.path.insert(0, r"S:\services\api-gateway")

GW = "http://127.0.0.1:7000"


@pytest.fixture
def client():
    return httpx.Client(base_url=GW, timeout=30)


# ── Health Supervisor ────────────────────────────────────────────────────────

def test_health_summary_endpoint(client):
    """GET /v1/health/summary returns overall and per-dep states."""
    r = client.get("/v1/health/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "overall_state" in data
    assert "dependencies" in data
    deps = data["dependencies"]
    # Should have the 5 monitored services
    assert len(deps) >= 5
    for name in ["model-router", "memory-engine", "pipecat", "openclaw", "eva-os"]:
        assert name in deps
        assert "state" in deps[name]
        assert "consecutive_failures" in deps[name]


def test_health_summary_has_valid_states(client):
    """All dependency states are valid SupervisorState values."""
    r = client.get("/v1/health/summary")
    data = r.json()
    valid_states = {"healthy", "degraded", "recovering", "failed"}
    assert data["overall_state"] in valid_states
    for dep in data["dependencies"].values():
        assert dep["state"] in valid_states


# ── Circuit Breaker ──────────────────────────────────────────────────────────

def test_breakers_endpoint(client):
    """GET /v1/breakers returns circuit breaker states."""
    r = client.get("/v1/breakers")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "breakers" in data
    # Should have at least the "openclaw" breaker
    assert "openclaw" in data["breakers"]
    openclaw_breaker = data["breakers"]["openclaw"]
    assert "state" in openclaw_breaker
    assert "stats" in openclaw_breaker


def test_breaker_starts_closed(client):
    """Circuit breaker starts in CLOSED state."""
    r = client.get("/v1/breakers")
    data = r.json()
    openclaw_breaker = data["breakers"]["openclaw"]
    assert openclaw_breaker["state"] == "closed"


def test_breaker_reset_nonexistent(client):
    """Resetting a nonexistent breaker returns 404."""
    r = client.post("/v1/breakers/nonexistent_service/reset")
    assert r.status_code == 404
    data = r.json()
    assert data["ok"] is False


def test_breaker_reset_openclaw(client):
    """POST /v1/breakers/openclaw/reset resets to CLOSED."""
    r = client.post("/v1/breakers/openclaw/reset")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["breaker"]["state"] == "closed"


# ── Dead Letter Queue ────────────────────────────────────────────────────────

def test_dead_letters_endpoint(client):
    """GET /v1/dead-letters returns list."""
    r = client.get("/v1/dead-letters")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "dead_letters" in data
    assert isinstance(data["dead_letters"], list)
    assert "total" in data


def test_dead_letter_get_nonexistent(client):
    """GET /v1/dead-letters/{bad_id} returns 404."""
    r = client.get("/v1/dead-letters/dl_nonexistent")
    assert r.status_code == 404
    data = r.json()
    assert data["ok"] is False


def test_dead_letter_replay_nonexistent(client):
    """POST /v1/dead-letters/{bad_id}/replay fails gracefully."""
    r = client.post("/v1/dead-letters/dl_nonexistent/replay")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "NOT_FOUND" in str(data.get("error", {}))


# ── Circuit Breaker Unit Tests ───────────────────────────────────────────────

def test_circuit_breaker_unit_failure_threshold():
    """Circuit breaker opens after failure_threshold consecutive failures."""
    from circuit_breaker import CircuitBreaker, BreakerConfig, CircuitOpenError, BreakerState

    async def _run():
        config = BreakerConfig(failure_threshold=3, recovery_timeout_s=60)
        cb = CircuitBreaker("test_dep", config)
        assert cb.state == BreakerState.CLOSED

        async def _fail():
            raise ValueError("Simulated failure")

        # Trip breaker with 3 failures
        for i in range(3):
            try:
                await cb.call(_fail)
            except ValueError:
                pass

        assert cb.state == BreakerState.OPEN
        assert cb.stats.trips == 1
        assert cb.stats.consecutive_failures == 3

        # Next call should raise CircuitOpenError
        try:
            await cb.call(_fail)
            assert False, "Should have raised CircuitOpenError"
        except CircuitOpenError:
            pass

    asyncio.get_event_loop().run_until_complete(_run())


def test_circuit_breaker_unit_reset():
    """Manual reset returns breaker to CLOSED."""
    from circuit_breaker import CircuitBreaker, BreakerConfig, BreakerState

    async def _run():
        config = BreakerConfig(failure_threshold=2)
        cb = CircuitBreaker("test_reset", config)

        async def _fail():
            raise ValueError("fail")

        for _ in range(2):
            try:
                await cb.call(_fail)
            except ValueError:
                pass

        assert cb.state == BreakerState.OPEN
        await cb.reset()
        assert cb.state == BreakerState.CLOSED
        assert cb.stats.consecutive_failures == 0

    asyncio.get_event_loop().run_until_complete(_run())


def test_circuit_breaker_unit_success_closes():
    """Breaker in HALF_OPEN closes after success_threshold successes."""
    from circuit_breaker import CircuitBreaker, BreakerConfig, BreakerState

    async def _run():
        config = BreakerConfig(
            failure_threshold=2,
            recovery_timeout_s=0,   # Immediate recovery for test
            max_jitter_s=0,         # No jitter for determinism
            success_threshold=2,
            half_open_max_calls=5,
        )
        cb = CircuitBreaker("test_halfopen", config)

        async def _fail():
            raise ValueError("fail")

        async def _succeed():
            return "ok"

        # Trip it open
        for _ in range(2):
            try:
                await cb.call(_fail)
            except ValueError:
                pass
        assert cb.state == BreakerState.OPEN

        # Wait for recovery (0s timeout + 0s jitter)
        import time
        time.sleep(0.05)

        # Calls should now succeed and close the breaker
        r1 = await cb.call(_succeed)
        assert r1 == "ok"
        # After 1 success, still half-open
        assert cb.state == BreakerState.HALF_OPEN

        r2 = await cb.call(_succeed)
        assert r2 == "ok"
        # After 2 successes (= success_threshold), should close
        assert cb.state == BreakerState.CLOSED

    asyncio.get_event_loop().run_until_complete(_run())


# ── Dead Letter Queue Unit Tests ─────────────────────────────────────────────

def test_dead_letter_queue_unit():
    """Dead letter queue basic operations."""
    from dead_letter import DeadLetterQueue

    async def _run():
        dlq = DeadLetterQueue()

        # Enqueue
        lid = await dlq.enqueue(
            action_id="act_test123",
            intent="file.write",
            params={"path": "/tmp/test.txt"},
            error_code="EXECUTION_FAILED",
            error_message="Test failure",
        )
        assert lid.startswith("dl_")

        # Get
        dl = await dlq.get(lid)
        assert dl is not None
        assert dl.action_id == "act_test123"
        assert dl.intent == "file.write"
        assert dl.replayed is False

        # List
        letters = await dlq.list_letters()
        assert len(letters) == 1

        # Count
        count = await dlq.count()
        assert count == 1

        # Mark replayed
        await dlq.mark_replayed(lid, "act_replay456")
        dl = await dlq.get(lid)
        assert dl.replayed is True
        assert dl.replay_action_id == "act_replay456"

        # Count excludes replayed by default
        count_active = await dlq.count(include_replayed=False)
        assert count_active == 0
        count_all = await dlq.count(include_replayed=True)
        assert count_all == 1

    asyncio.get_event_loop().run_until_complete(_run())


def test_dead_letter_queue_bounded():
    """Dead letter queue evicts oldest when over MAX_DEAD_LETTERS."""
    from dead_letter import DeadLetterQueue, MAX_DEAD_LETTERS

    async def _run():
        dlq = DeadLetterQueue()
        first_lid = None

        for i in range(MAX_DEAD_LETTERS + 5):
            lid = await dlq.enqueue(
                action_id=f"act_{i}",
                intent="test.action",
                params={},
                error_code="FAIL",
                error_message=f"fail {i}",
            )
            if i == 0:
                first_lid = lid

        # Should be bounded
        count = await dlq.count(include_replayed=True)
        assert count == MAX_DEAD_LETTERS

        # First entry should have been evicted
        assert await dlq.get(first_lid) is None

    asyncio.get_event_loop().run_until_complete(_run())


# ── Health Supervisor Unit Tests ─────────────────────────────────────────────

def test_health_supervisor_state_machine():
    """Health supervisor transitions dependency states correctly."""
    from health_supervisor import (
        DependencyHealth, SupervisorState,
        DEGRADED_AFTER_FAILURES, FAILED_AFTER_FAILURES, HEALTHY_AFTER_SUCCESSES,
        HealthSupervisor,
    )

    dep = DependencyHealth("test-dep", 9999)
    assert dep.state == SupervisorState.HEALTHY

    # Simulate 3 consecutive failures → degraded
    sv = HealthSupervisor()
    dep.consecutive_failures = DEGRADED_AFTER_FAILURES
    dep.consecutive_successes = 0
    sv._update_dep_state(dep)
    assert dep.state == SupervisorState.DEGRADED

    # Simulate 10 consecutive failures → failed
    dep.consecutive_failures = FAILED_AFTER_FAILURES
    sv._update_dep_state(dep)
    assert dep.state == SupervisorState.FAILED

    # Simulate recovery: 1 success → recovering
    dep.consecutive_failures = 0
    dep.consecutive_successes = 1
    sv._update_dep_state(dep)
    assert dep.state == SupervisorState.RECOVERING

    # 3 successes → healthy
    dep.consecutive_successes = HEALTHY_AFTER_SUCCESSES
    sv._update_dep_state(dep)
    assert dep.state == SupervisorState.HEALTHY


def test_health_supervisor_overall_state():
    """Overall state reflects worst dependency state."""
    from health_supervisor import HealthSupervisor, SupervisorState

    sv = HealthSupervisor()
    # All healthy initially
    sv._update_overall_state()
    assert sv.overall_state == SupervisorState.HEALTHY

    # Force one dep to degraded
    dep = list(sv._deps.values())[0]
    dep.state = SupervisorState.DEGRADED
    sv._update_overall_state()
    assert sv.overall_state == SupervisorState.DEGRADED

    # Force one dep to failed
    dep.state = SupervisorState.FAILED
    sv._update_overall_state()
    assert sv.overall_state == SupervisorState.FAILED


# ── Integration: Failed action lands in dead letter ──────────────────────────

def test_failed_action_with_unimplemented_does_not_dead_letter(client):
    """Unimplemented intent fails at validation — no dead letter created."""
    # Get current DL count
    dl_before = client.get("/v1/dead-letters").json()["total"]

    body = {"intent": "app.launch", "params": {"target": "notepad.exe"}}
    r = client.post("/v1/actions/plan", json=body)
    data = r.json()
    assert data["ok"] is False
    assert "Not implemented" in data["error"]["message"]

    # DL count should not increase (validation failure, not execution failure)
    dl_after = client.get("/v1/dead-letters").json()["total"]
    assert dl_after == dl_before


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
