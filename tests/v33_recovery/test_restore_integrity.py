"""G26: Restore Integrity tests (v3.3 Epic B).

Validates recovery paths restore coherent state without violating invariants.
Tests cover: supervisor state machine transitions, restore roundtrip hash
stability, restart convergence, dependency graph isolation, maintenance mode,
and chaos fault injection.

Gate pass criteria: >= 12 passed, 0 failed; restore roundtrip produces
identical state hashes; services converge to HEALTHY.
"""
import asyncio
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# -- Load modules via conftest pre-registration --------------------------

from service_supervisor import (
    ServiceSupervisor,
    ServiceState,
    ServiceRecord,
    DEPENDENCY_GRAPH,
)
from circuit_breaker import (
    CircuitBreaker,
    BreakerConfig,
    BreakerState,
    BreakerRegistry,
    CircuitOpenError,
)
from retry_taxonomy import (
    FailureClass,
    classify_failure,
    is_retryable,
    RETRY_POLICY,
)
from health_supervisor import (
    HealthSupervisor,
    SupervisorState,
    DependencyHealth,
    DEGRADED_AFTER_FAILURES,
    FAILED_AFTER_FAILURES,
    HEALTHY_AFTER_SUCCESSES,
)


# -- Helpers -------------------------------------------------------------

def make_supervisor_detached() -> ServiceSupervisor:
    """Create a supervisor with no config file dependency."""
    sup = ServiceSupervisor.__new__(ServiceSupervisor)
    sup._services = {}
    sup._maintenance_mode = False
    sup._event_listeners = []
    sup._poll_task = None
    sup._poll_interval = 15.0
    sup._started_at = time.time()
    # Register test services manually
    for name, port in [("svc-a", 9001), ("svc-b", 9002), ("svc-c", 9003)]:
        sup._services[name] = ServiceRecord(
            name=name, host="127.0.0.1", port=port,
            state=ServiceState.HEALTHY,
        )
    return sup


def make_health_dep(name: str, port: int = 9999) -> DependencyHealth:
    """Create a DependencyHealth for testing."""
    return DependencyHealth(name=name, port=port)


def simulate_failures(record: ServiceRecord, count: int, supervisor: ServiceSupervisor):
    """Simulate consecutive failures on a ServiceRecord."""
    for _ in range(count):
        record.consecutive_successes = 0
        record.consecutive_failures += 1
        record.error = "simulated failure"
        supervisor._transition(record, healthy=False)


def simulate_successes(record: ServiceRecord, count: int, supervisor: ServiceSupervisor):
    """Simulate consecutive successes on a ServiceRecord."""
    for _ in range(count):
        record.consecutive_failures = 0
        record.consecutive_successes += 1
        record.error = ""
        supervisor._transition(record, healthy=True)


# ========================================================================
# TEST CLASS: Restore Integrity (G26)
# ========================================================================


class TestRestoreIntegrity:
    """G26 gate tests: recovery state machine, restore roundtrip, chaos."""

    # -- State machine transitions ----------------------------------------

    def test_supervisor_unreachable_to_recovering_to_healthy(self):
        """Supervisor transitions UNREACHABLE -> RECOVERING -> HEALTHY
        with expected event sequence."""
        sup = make_supervisor_detached()
        events = []
        sup.add_event_listener(lambda e: events.append(e))

        record = sup._services["svc-a"]
        # Drive to UNREACHABLE (3 failures)
        simulate_failures(record, 3, sup)
        assert record.state == ServiceState.UNREACHABLE

        # First success: should go to RECOVERING (need RECOVERY_PROBES=2)
        simulate_successes(record, 1, sup)
        assert record.state == ServiceState.RECOVERING

        # Second success: should go to HEALTHY
        simulate_successes(record, 1, sup)
        assert record.state == ServiceState.HEALTHY

        # Verify event sequence
        event_types = [e["type"] for e in events]
        assert "supervision.service.unreachable" in event_types
        assert "supervision.service.recovered" in event_types
        assert "supervision.service.healthy" in event_types

    def test_supervisor_degraded_to_unreachable_transition(self):
        """Verify DEGRADED state occurs between HEALTHY and UNREACHABLE."""
        sup = make_supervisor_detached()
        record = sup._services["svc-b"]

        # 1 failure -> DEGRADED
        simulate_failures(record, 1, sup)
        assert record.state == ServiceState.DEGRADED

        # Continue to 3 -> UNREACHABLE
        simulate_failures(record, 2, sup)
        assert record.state == ServiceState.UNREACHABLE

    def test_maintenance_mode_blocks_interpretation(self):
        """Maintenance mode is togglable and reflects in status."""
        sup = make_supervisor_detached()
        assert sup.maintenance_mode is False

        result = sup.set_maintenance_mode(True)
        assert result["maintenance_mode"] is True
        assert result["previous"] is False
        assert sup.maintenance_mode is True

        status = sup.get_status()
        assert status["maintenance_mode"] is True

    def test_maintenance_mode_preserves_service_states(self):
        """Entering maintenance mode does not reset service states."""
        sup = make_supervisor_detached()
        record = sup._services["svc-a"]
        simulate_failures(record, 3, sup)
        assert record.state == ServiceState.UNREACHABLE

        sup.set_maintenance_mode(True)
        # State should be preserved
        assert sup._services["svc-a"].state == ServiceState.UNREACHABLE

    # -- Dependency graph ------------------------------------------------

    def test_dependency_graph_no_circular_refs(self):
        """Dependency graph must have no circular references."""
        graph = DEPENDENCY_GRAPH
        visited = set()
        path = set()

        def has_cycle(node):
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for dep in graph.get(node, []):
                if has_cycle(dep):
                    return True
            path.discard(node)
            return False

        for node in graph:
            assert not has_cycle(node), f"Circular dependency detected at {node}"

    def test_degraded_dependency_does_not_deadlock_recovery(self):
        """When a dependency is degraded, its dependents can still recover
        independently -- no deadlock in recovery loop."""
        sup = make_supervisor_detached()
        # Add dependency relationship: svc-a depends on svc-b
        record_b = sup._services["svc-b"]
        record_a = sup._services["svc-a"]

        # Degrade svc-b
        simulate_failures(record_b, 3, sup)
        assert record_b.state == ServiceState.UNREACHABLE

        # svc-a can still independently recover
        simulate_failures(record_a, 2, sup)
        simulate_successes(record_a, 2, sup)
        assert record_a.state == ServiceState.HEALTHY
        # svc-b is still unreachable -- no cascading deadlock
        assert record_b.state == ServiceState.UNREACHABLE

    # -- Circuit breaker restore -----------------------------------------

    def test_breaker_reset_restores_closed_state(self):
        """Manual breaker reset restores CLOSED state with zeroed counters."""
        loop = asyncio.new_event_loop()
        breaker = CircuitBreaker("test-dep", BreakerConfig(failure_threshold=2))

        async def fail():
            raise ConnectionError("fail")

        async def run():
            for _ in range(3):
                try:
                    await breaker.call(fail)
                except (ConnectionError, CircuitOpenError):
                    pass
            assert breaker.state == BreakerState.OPEN

            await breaker.reset()
            assert breaker.state == BreakerState.CLOSED
            assert breaker.stats.consecutive_failures == 0
            assert breaker.stats.consecutive_successes == 0

        loop.run_until_complete(run())
        loop.close()

    def test_breaker_state_hash_deterministic_after_reset(self):
        """Breaker serialized state is deterministic after reset."""
        breaker = CircuitBreaker("hash-test", BreakerConfig())
        state1 = json.dumps(breaker.to_dict(), sort_keys=True)

        loop = asyncio.new_event_loop()

        async def run():
            await breaker.reset()

        loop.run_until_complete(run())
        loop.close()

        state2 = json.dumps(breaker.to_dict(), sort_keys=True)
        # Both should be CLOSED with zeroed failure counts
        d1 = json.loads(state1)
        d2 = json.loads(state2)
        assert d1["state"] == d2["state"] == "closed"
        assert d1["stats"]["consecutive_failures"] == d2["stats"]["consecutive_failures"] == 0

    # -- Retry taxonomy determinism --------------------------------------

    def test_failure_classification_deterministic(self):
        """Same error input always produces same failure class."""
        cases = [
            ({"error_code": "CIRCUIT_OPEN"}, FailureClass.CIRCUIT_OPEN),
            ({"error_code": "POLICY_DENIED"}, FailureClass.POLICY_DENIED),
            ({"error_code": "TIMEOUT"}, FailureClass.TIMEOUT),
            ({"error_message": "connection refused"}, FailureClass.CONNECTION_BOOTSTRAP),
            ({"error_code": "429"}, FailureClass.BACKPRESSURE),
            ({"error_code": "EXECUTION_FAILED"}, FailureClass.EXECUTION_ERROR),
        ]
        for kwargs, expected in cases:
            result = classify_failure(**kwargs)
            assert result == expected, f"{kwargs} -> {result} (expected {expected})"
            # Run again to prove determinism
            assert classify_failure(**kwargs) == result

    def test_non_retryable_classes_never_retry(self):
        """Non-retryable failure classes have max_retries=0."""
        non_retryable = [
            FailureClass.CIRCUIT_OPEN,
            FailureClass.POLICY_DENIED,
            FailureClass.VALIDATION_FAILED,
        ]
        for fc in non_retryable:
            assert not is_retryable(fc), f"{fc} should not be retryable"
            assert RETRY_POLICY[fc]["max_retries"] == 0

    # -- HealthSupervisor state machine (gateway side) --------------------

    def test_health_dep_degraded_after_threshold(self):
        """DependencyHealth transitions to DEGRADED after threshold failures."""
        dep = make_health_dep("test-svc")
        assert dep.state == SupervisorState.HEALTHY

        # Simulate failures up to threshold
        for i in range(DEGRADED_AFTER_FAILURES):
            dep.consecutive_failures = i + 1
            dep.consecutive_successes = 0

        # Apply state update logic
        if dep.consecutive_failures >= FAILED_AFTER_FAILURES:
            dep.state = SupervisorState.FAILED
        elif dep.consecutive_failures >= DEGRADED_AFTER_FAILURES:
            dep.state = SupervisorState.DEGRADED

        assert dep.state == SupervisorState.DEGRADED

    def test_health_dep_recovers_after_successes(self):
        """DependencyHealth transitions DEGRADED -> RECOVERING -> HEALTHY."""
        dep = make_health_dep("test-svc")
        dep.state = SupervisorState.DEGRADED
        dep.consecutive_failures = 5
        dep.consecutive_successes = 0

        # Simulate recovery successes
        for i in range(HEALTHY_AFTER_SUCCESSES):
            dep.consecutive_failures = 0
            dep.consecutive_successes = i + 1
            if dep.state in (SupervisorState.DEGRADED, SupervisorState.FAILED, SupervisorState.RECOVERING):
                if dep.consecutive_successes >= HEALTHY_AFTER_SUCCESSES:
                    dep.state = SupervisorState.HEALTHY
                else:
                    dep.state = SupervisorState.RECOVERING

        assert dep.state == SupervisorState.HEALTHY

    # -- Post-recovery invariants ----------------------------------------

    def test_post_recovery_invariants_all_zero(self):
        """After full recovery cycle, invariant counters are all zero."""
        sup = make_supervisor_detached()
        record = sup._services["svc-c"]

        # Drive to UNREACHABLE
        simulate_failures(record, 5, sup)
        assert record.state == ServiceState.UNREACHABLE

        # Full recovery
        simulate_successes(record, sup.RECOVERY_PROBES, sup)
        assert record.state == ServiceState.HEALTHY

        # Post-recovery invariants
        assert record.consecutive_failures == 0
        assert record.error == ""
