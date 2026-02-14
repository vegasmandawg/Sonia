"""
v2.9 EVA-OS Supervision Integration Tests

Tests:
1. Service state machine transitions (healthy/degraded/unreachable/recovering)
2. Real probe behavior (success/failure/timeout)
3. Event emission on state changes
4. Dependency graph correctness
5. Maintenance mode toggle
6. Recovery detection
7. No hardcoded health data
"""

import sys
import os
import unittest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, r"S:\services\eva-os")
sys.path.insert(0, r"S:\services\shared")


def run_async(coro):
    """Helper to run async code in sync tests."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestServiceSupervisor(unittest.TestCase):
    """Core supervisor unit tests."""

    def _make_supervisor(self):
        from service_supervisor import ServiceSupervisor
        sup = ServiceSupervisor.__new__(ServiceSupervisor)
        sup._services = {}
        sup._maintenance_mode = False
        sup._event_listeners = []
        sup._poll_task = None
        sup._poll_interval = 15.0
        sup._started_at = time.time()
        # Load services from config
        sup._load_services(r"S:\config\sonia-config.json")
        return sup

    def test_loads_services_from_config(self):
        """Supervisor loads 5 downstream services from config."""
        sup = self._make_supervisor()
        self.assertEqual(len(sup.services), 5)
        expected = {"api-gateway", "model-router", "memory-engine", "pipecat", "openclaw"}
        self.assertEqual(set(sup.services.keys()), expected)

    def test_initial_state_is_unknown(self):
        """All services start in UNKNOWN state."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        for name, record in sup.services.items():
            self.assertEqual(record.state, ServiceState.UNKNOWN, f"{name} should be UNKNOWN")

    def test_dependency_graph_structure(self):
        """Dependency graph has correct structure."""
        sup = self._make_supervisor()
        graph = sup.get_dependency_graph()
        self.assertIn("api-gateway", graph)
        self.assertIn("model-router", graph["api-gateway"])
        self.assertIn("memory-engine", graph["api-gateway"])
        self.assertEqual(graph["openclaw"], [])

    def test_maintenance_mode_toggle(self):
        """Maintenance mode toggles correctly."""
        sup = self._make_supervisor()
        self.assertFalse(sup.maintenance_mode)

        result = sup.set_maintenance_mode(True)
        self.assertTrue(sup.maintenance_mode)
        self.assertTrue(result["maintenance_mode"])
        self.assertFalse(result["previous"])

        result = sup.set_maintenance_mode(False)
        self.assertFalse(sup.maintenance_mode)
        self.assertTrue(result["previous"])


class TestStateTransitions(unittest.TestCase):
    """State machine transition tests."""

    def _make_supervisor(self):
        from service_supervisor import ServiceSupervisor
        sup = ServiceSupervisor.__new__(ServiceSupervisor)
        sup._services = {}
        sup._maintenance_mode = False
        sup._event_listeners = []
        sup._poll_task = None
        sup._poll_interval = 15.0
        sup._started_at = time.time()
        sup._load_services(r"S:\config\sonia-config.json")
        return sup

    def test_healthy_on_first_success(self):
        """Two consecutive successes transition UNKNOWN -> RECOVERING -> HEALTHY."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        record = sup._services["api-gateway"]

        # First success: UNKNOWN -> RECOVERING
        record.consecutive_successes = 1
        sup._transition(record, healthy=True)
        self.assertEqual(record.state, ServiceState.RECOVERING)

        # Second success: RECOVERING -> HEALTHY
        record.consecutive_successes = 2
        sup._transition(record, healthy=True)
        self.assertEqual(record.state, ServiceState.HEALTHY)

    def test_degraded_on_first_failure(self):
        """Single failure transitions to DEGRADED."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        record = sup._services["model-router"]
        record.state = ServiceState.HEALTHY

        record.consecutive_failures = 1
        sup._transition(record, healthy=False)
        self.assertEqual(record.state, ServiceState.DEGRADED)

    def test_unreachable_on_three_failures(self):
        """Three consecutive failures transition to UNREACHABLE."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        record = sup._services["memory-engine"]
        record.state = ServiceState.HEALTHY

        record.consecutive_failures = 3
        sup._transition(record, healthy=False)
        self.assertEqual(record.state, ServiceState.UNREACHABLE)

    def test_recovery_from_unreachable(self):
        """Service recovers: UNREACHABLE -> RECOVERING -> HEALTHY."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        record = sup._services["pipecat"]
        record.state = ServiceState.UNREACHABLE
        record.consecutive_failures = 5

        # First success
        record.consecutive_successes = 1
        record.consecutive_failures = 0
        sup._transition(record, healthy=True)
        self.assertEqual(record.state, ServiceState.RECOVERING)

        # Second success
        record.consecutive_successes = 2
        sup._transition(record, healthy=True)
        self.assertEqual(record.state, ServiceState.HEALTHY)


class TestEventEmission(unittest.TestCase):
    """Event emission on state transitions."""

    def _make_supervisor(self):
        from service_supervisor import ServiceSupervisor
        sup = ServiceSupervisor.__new__(ServiceSupervisor)
        sup._services = {}
        sup._maintenance_mode = False
        sup._event_listeners = []
        sup._poll_task = None
        sup._poll_interval = 15.0
        sup._started_at = time.time()
        sup._load_services(r"S:\config\sonia-config.json")
        return sup

    def test_event_emitted_on_state_change(self):
        """State transition emits supervisory event."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        events = []
        sup.add_event_listener(lambda e: events.append(e))

        record = sup._services["api-gateway"]
        record.state = ServiceState.HEALTHY
        record.consecutive_failures = 1
        sup._transition(record, healthy=False)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "supervision.service.degraded")
        self.assertEqual(events[0]["service"], "api-gateway")
        self.assertEqual(events[0]["payload"]["old_state"], "healthy")
        self.assertEqual(events[0]["payload"]["new_state"], "degraded")

    def test_no_event_on_same_state(self):
        """No event when state doesn't change."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        events = []
        sup.add_event_listener(lambda e: events.append(e))

        record = sup._services["model-router"]
        record.state = ServiceState.HEALTHY
        record.consecutive_successes = 5
        sup._transition(record, healthy=True)

        self.assertEqual(len(events), 0)

    def test_unreachable_event(self):
        """UNREACHABLE state emits supervision.service.unreachable."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        events = []
        sup.add_event_listener(lambda e: events.append(e))

        record = sup._services["openclaw"]
        record.state = ServiceState.DEGRADED
        record.consecutive_failures = 3
        sup._transition(record, healthy=False)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "supervision.service.unreachable")

    def test_recovery_event(self):
        """Recovery emits supervision.service.recovered."""
        from service_supervisor import ServiceState
        sup = self._make_supervisor()
        events = []
        sup.add_event_listener(lambda e: events.append(e))

        record = sup._services["memory-engine"]
        record.state = ServiceState.UNREACHABLE
        record.consecutive_successes = 1
        sup._transition(record, healthy=True)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "supervision.service.recovered")

    def test_maintenance_toggle_event(self):
        """Maintenance mode toggle emits event."""
        sup = self._make_supervisor()
        events = []
        sup.add_event_listener(lambda e: events.append(e))

        sup.set_maintenance_mode(True)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "supervision.maintenance.toggled")
        self.assertTrue(events[0]["payload"]["new"])


class TestProbeService(unittest.TestCase):
    """Async probe tests."""

    def _make_supervisor(self):
        from service_supervisor import ServiceSupervisor
        sup = ServiceSupervisor.__new__(ServiceSupervisor)
        sup._services = {}
        sup._maintenance_mode = False
        sup._event_listeners = []
        sup._poll_task = None
        sup._poll_interval = 15.0
        sup._started_at = time.time()
        sup._load_services(r"S:\config\sonia-config.json")
        return sup

    @patch("service_supervisor.httpx.AsyncClient")
    def test_probe_success(self, mock_client_class):
        """Successful probe updates record correctly."""
        from service_supervisor import ServiceState

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        sup = self._make_supervisor()

        async def _test():
            record = await sup.probe_service("api-gateway")
            return record

        record = run_async(_test())
        self.assertEqual(record.consecutive_successes, 1)
        self.assertEqual(record.consecutive_failures, 0)
        self.assertEqual(record.error, "")

    @patch("service_supervisor.httpx.AsyncClient")
    def test_probe_failure(self, mock_client_class):
        """Failed probe updates failure count."""
        from service_supervisor import ServiceState
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        sup = self._make_supervisor()

        async def _test():
            record = await sup.probe_service("model-router")
            return record

        record = run_async(_test())
        self.assertEqual(record.consecutive_failures, 1)
        self.assertIn("refused", record.error)

    def test_probe_unknown_service_raises(self):
        """Probing unknown service raises ValueError."""
        sup = self._make_supervisor()

        async def _test():
            await sup.probe_service("nonexistent")

        with self.assertRaises(ValueError):
            run_async(_test())


class TestNoHardcodedData(unittest.TestCase):
    """Verify main.py has no hardcoded health data."""

    def test_no_hardcoded_service_health_in_main(self):
        """main.py /status and /health/all use supervisor, not hardcoded dicts."""
        with open(r"S:\services\eva-os\main.py", "r") as f:
            source = f.read()

        # Old hardcoded patterns should be gone
        self.assertNotIn('"latency_ms": 10', source,
                         "main.py still has hardcoded latency values")
        self.assertNotIn('"latency_ms": 8', source)
        self.assertNotIn('"latency_ms": 15', source)
        self.assertNotIn('"latency_ms": 12', source)
        self.assertNotIn('"latency_ms": 20', source)

    def test_status_endpoint_uses_supervisor(self):
        """The /status endpoint references _supervisor, not hardcoded dict."""
        with open(r"S:\services\eva-os\main.py", "r") as f:
            source = f.read()
        self.assertIn("_supervisor", source)
        self.assertIn("get_status", source)

    def test_health_all_endpoint_uses_probe(self):
        """The /health/all endpoint calls probe_all, not returns static data."""
        with open(r"S:\services\eva-os\main.py", "r") as f:
            source = f.read()
        self.assertIn("probe_all", source)


if __name__ == "__main__":
    unittest.main()
