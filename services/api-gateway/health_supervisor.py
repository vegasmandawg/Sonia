"""
Stage 5 M2 — Health Supervisor
Background loop that monitors dependency health and maintains a state machine:
  healthy → degraded → recovering → healthy | failed
"""

import asyncio
import time
import httpx
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime
from jsonl_logger import JsonlLogger


class SupervisorState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAILED = "failed"


class DependencyHealth:
    """Health status for a single dependency."""

    def __init__(self, name: str, port: int, healthz_path: str = "/healthz"):
        self.name = name
        self.port = port
        self.healthz_path = healthz_path
        self.state = SupervisorState.HEALTHY
        self.last_check_time: Optional[float] = None
        self.last_ok_time: Optional[float] = None
        self.last_fail_time: Optional[float] = None
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self.total_checks: int = 0
        self.total_failures: int = 0
        self.last_latency_ms: float = 0.0
        self.last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "port": self.port,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "last_latency_ms": self.last_latency_ms,
            "last_error": self.last_error,
            "last_check_time": self.last_check_time,
            "last_ok_time": self.last_ok_time,
        }


# Thresholds
DEGRADED_AFTER_FAILURES = 3
FAILED_AFTER_FAILURES = 10
HEALTHY_AFTER_SUCCESSES = 3


class HealthSupervisor:
    """
    Background health monitor for all Sonia dependencies.
    Runs a periodic check loop (default 15s interval).
    """

    def __init__(self, check_interval_s: float = 15.0):
        self.check_interval = check_interval_s
        self._deps: Dict[str, DependencyHealth] = {}
        self._overall_state = SupervisorState.HEALTHY
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._logger = JsonlLogger("health_supervisor")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(3.0))

        # Register core dependencies
        self._register_defaults()

    def _register_defaults(self):
        """Register the 6 core Sonia services as dependencies."""
        for name, port in [
            ("model-router", 7010),
            ("memory-engine", 7020),
            ("pipecat", 7030),
            ("openclaw", 7040),
            ("eva-os", 7050),
        ]:
            self._deps[name] = DependencyHealth(name, port)

    async def check_dependency(self, dep: DependencyHealth):
        """Perform a single health check on a dependency."""
        url = f"http://127.0.0.1:{dep.port}{dep.healthz_path}"
        t0 = time.time()
        dep.total_checks += 1
        dep.last_check_time = t0

        try:
            resp = await self._client.get(url)
            elapsed = round((time.time() - t0) * 1000, 2)
            dep.last_latency_ms = elapsed

            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok", False):
                    dep.consecutive_successes += 1
                    dep.consecutive_failures = 0
                    dep.last_ok_time = time.time()
                    dep.last_error = None
                    self._update_dep_state(dep)
                    return
            # Non-200 or not ok
            dep.consecutive_failures += 1
            dep.consecutive_successes = 0
            dep.total_failures += 1
            dep.last_fail_time = time.time()
            dep.last_error = f"HTTP {resp.status_code}"
            self._update_dep_state(dep)

        except Exception as e:
            elapsed = round((time.time() - t0) * 1000, 2)
            dep.last_latency_ms = elapsed
            dep.consecutive_failures += 1
            dep.consecutive_successes = 0
            dep.total_failures += 1
            dep.last_fail_time = time.time()
            dep.last_error = str(e)[:200]
            self._update_dep_state(dep)

    def _update_dep_state(self, dep: DependencyHealth):
        """Update dependency state based on failure/success counts."""
        prev_state = dep.state

        if dep.consecutive_failures >= FAILED_AFTER_FAILURES:
            dep.state = SupervisorState.FAILED
        elif dep.consecutive_failures >= DEGRADED_AFTER_FAILURES:
            dep.state = SupervisorState.DEGRADED
        elif dep.state in (SupervisorState.DEGRADED, SupervisorState.FAILED, SupervisorState.RECOVERING):
            if dep.consecutive_successes >= HEALTHY_AFTER_SUCCESSES:
                dep.state = SupervisorState.HEALTHY
            else:
                dep.state = SupervisorState.RECOVERING
        else:
            dep.state = SupervisorState.HEALTHY

        if dep.state != prev_state:
            self._logger.log({
                "event": "state_change",
                "dependency": dep.name,
                "from": prev_state.value,
                "to": dep.state.value,
                "consecutive_failures": dep.consecutive_failures,
            })

    async def check_all(self):
        """Run health checks on all dependencies concurrently."""
        tasks = [self.check_dependency(dep) for dep in self._deps.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._update_overall_state()

    def _update_overall_state(self):
        """Compute overall system state from dependency states."""
        states = [dep.state for dep in self._deps.values()]
        prev = self._overall_state

        if any(s == SupervisorState.FAILED for s in states):
            self._overall_state = SupervisorState.FAILED
        elif any(s == SupervisorState.DEGRADED for s in states):
            self._overall_state = SupervisorState.DEGRADED
        elif any(s == SupervisorState.RECOVERING for s in states):
            self._overall_state = SupervisorState.RECOVERING
        else:
            self._overall_state = SupervisorState.HEALTHY

        if self._overall_state != prev:
            self._logger.log({
                "event": "overall_state_change",
                "from": prev.value,
                "to": self._overall_state.value,
            })

    async def start(self):
        """Start the background check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        """Stop the background check loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._client.aclose()

    async def _loop(self):
        """Main supervisor loop."""
        while self._running:
            try:
                await self.check_all()
            except Exception:
                pass
            await asyncio.sleep(self.check_interval)

    # ── Observability ────────────────────────────────────────────────────

    @property
    def overall_state(self) -> SupervisorState:
        return self._overall_state

    def summary(self) -> Dict[str, Any]:
        return {
            "overall_state": self._overall_state.value,
            "dependencies": {
                name: dep.to_dict()
                for name, dep in self._deps.items()
            },
        }

    def get_dep(self, name: str) -> Optional[DependencyHealth]:
        return self._deps.get(name)


# ── Singleton ────────────────────────────────────────────────────────────────

_supervisor: Optional[HealthSupervisor] = None


def get_health_supervisor() -> HealthSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = HealthSupervisor()
    return _supervisor
