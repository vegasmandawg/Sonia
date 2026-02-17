"""
EVA-OS Service Supervisor -- Real health probing and state machine

Replaces hardcoded health data with active /healthz probes.
Per-service state machine: healthy -> degraded -> unreachable -> recovering.
Emits supervisory events via shared EventEnvelope.
"""

import asyncio
import time
import logging
import json
import subprocess
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger("eva-os.supervisor")


class ServiceState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


@dataclass
class ServiceRecord:
    """Tracks state for a single downstream service."""
    name: str
    host: str
    port: int
    health_endpoint: str = "/healthz"
    state: ServiceState = ServiceState.UNKNOWN
    last_check: float = 0.0
    last_healthy: float = 0.0
    latency_ms: float = 0.0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    error: str = ""

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self.health_endpoint}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "latency_ms": round(self.latency_ms, 1),
            "last_check": self.last_check,
            "last_healthy": self.last_healthy,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "error": self.error,
        }


# Dependency graph: service -> list of services it depends on
DEPENDENCY_GRAPH = {
    "api-gateway": ["model-router", "memory-engine"],
    "pipecat": ["api-gateway"],
    "openclaw": [],
    "model-router": [],
    "memory-engine": [],
    "eva-os": [],
    "orchestrator": ["api-gateway", "openclaw", "memory-engine"],
    "vision-capture": [],
    "perception": ["vision-capture"],
}


class ServiceSupervisor:
    """
    Active health supervision for all Sonia services.

    Polls /healthz endpoints, maintains per-service state machine,
    and emits events on state transitions.
    """

    DEGRADATION_THRESHOLD_S = 60.0  # consecutive failure time before degraded -> unreachable
    RECOVERY_PROBES = 2  # consecutive successes to recover

    def __init__(self, config_path: str = r"S:\config\sonia-config.json"):
        self._services: Dict[str, ServiceRecord] = {}
        self._maintenance_mode = False
        self._event_listeners: List[Callable] = []
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval = 15.0  # seconds
        self._started_at = time.time()

        self._load_services(config_path)

    def _load_services(self, config_path: str):
        """Load service definitions from sonia-config.json."""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            logger.warning("Could not load config: %s, using defaults", e)
            cfg = {}

        services_cfg = cfg.get("services", {})

        # Map config keys to service records
        defaults = {
            "api_gateway": ("api-gateway", "127.0.0.1", 7000),
            "model_router": ("model-router", "127.0.0.1", 7010),
            "memory_engine": ("memory-engine", "127.0.0.1", 7020),
            "pipecat": ("pipecat", "127.0.0.1", 7030),
            "openclaw": ("openclaw", "127.0.0.1", 7040),
            "orchestrator": ("orchestrator", "127.0.0.1", 8000),
            "vision_capture": ("vision-capture", "127.0.0.1", 7060),
            "perception": ("perception", "127.0.0.1", 7070),
        }

        for cfg_key, (name, default_host, default_port) in defaults.items():
            svc = services_cfg.get(cfg_key, {})
            self._services[name] = ServiceRecord(
                name=name,
                host=svc.get("host", default_host),
                port=svc.get("port", default_port),
                health_endpoint=svc.get("health_endpoint", "/healthz"),
            )

    def add_event_listener(self, callback: Callable):
        """Register a callback for supervisory events."""
        self._event_listeners.append(callback)

    def _emit_event(self, event_type: str, service_name: str, payload: Dict[str, Any]):
        """Emit a supervisory event to all listeners."""
        event = {
            "type": event_type,
            "source": "eva-os",
            "service": service_name,
            "timestamp": time.time(),
            "payload": payload,
        }
        for listener in self._event_listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error("Event listener error: %s", e)
        logger.info("Supervision event: %s for %s", event_type, service_name)

    async def probe_service(self, name: str) -> ServiceRecord:
        """Probe a single service's /healthz endpoint."""
        record = self._services.get(name)
        if not record:
            raise ValueError(f"Unknown service: {name}")

        start = time.monotonic()
        record.last_check = time.time()

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(record.url, timeout=5.0)
                elapsed_ms = (time.monotonic() - start) * 1000
                record.latency_ms = elapsed_ms

                if resp.status_code == 200:
                    record.error = ""
                    record.consecutive_failures = 0
                    record.consecutive_successes += 1
                    record.last_healthy = time.time()
                    self._transition(record, healthy=True)
                else:
                    record.error = f"HTTP {resp.status_code}"
                    record.consecutive_successes = 0
                    record.consecutive_failures += 1
                    self._transition(record, healthy=False)

        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            record.latency_ms = elapsed_ms
            record.error = str(e)
            record.consecutive_successes = 0
            record.consecutive_failures += 1
            self._transition(record, healthy=False)

        return record

    def _transition(self, record: ServiceRecord, healthy: bool):
        """Apply state machine transition and emit events."""
        old_state = record.state

        if healthy:
            if old_state in (ServiceState.UNREACHABLE, ServiceState.DEGRADED, ServiceState.UNKNOWN):
                if record.consecutive_successes >= self.RECOVERY_PROBES:
                    record.state = ServiceState.HEALTHY
                else:
                    record.state = ServiceState.RECOVERING
            elif old_state == ServiceState.RECOVERING:
                if record.consecutive_successes >= self.RECOVERY_PROBES:
                    record.state = ServiceState.HEALTHY
            else:
                record.state = ServiceState.HEALTHY
        else:
            if record.consecutive_failures >= 3:
                record.state = ServiceState.UNREACHABLE
            elif record.consecutive_failures >= 1:
                record.state = ServiceState.DEGRADED

        # Emit event on state change
        if record.state != old_state:
            event_map = {
                ServiceState.HEALTHY: "supervision.service.healthy",
                ServiceState.DEGRADED: "supervision.service.degraded",
                ServiceState.UNREACHABLE: "supervision.service.unreachable",
                ServiceState.RECOVERING: "supervision.service.recovered",
            }
            event_type = event_map.get(record.state)
            if event_type:
                self._emit_event(event_type, record.name, {
                    "old_state": old_state.value,
                    "new_state": record.state.value,
                    "consecutive_failures": record.consecutive_failures,
                    "error": record.error,
                })

        # v4.4 Epic C: Health-driven auto_restart on UNREACHABLE
        if record.state == ServiceState.UNREACHABLE and old_state != ServiceState.UNREACHABLE:
            asyncio.ensure_future(self._auto_restart(record.name))

    async def _auto_restart(self, service_name: str):
        """Trigger automatic restart when service enters UNREACHABLE state."""
        logger.info("Auto-restart triggered for %s (health-driven)", service_name)
        try:
            result = await self.restart_service(service_name)
            if result.get("ok"):
                logger.info("Auto-restart succeeded for %s (pid=%s)", service_name, result.get("pid"))
            else:
                logger.warning("Auto-restart failed for %s: %s", service_name, result.get("error"))
        except Exception as e:
            logger.error("Auto-restart error for %s: %s", service_name, e)

    # ── Restart Support (v4.4 Epic C) ────────────────────────────────

    # Canonical uvicorn commands for each service
    SERVICE_COMMANDS = {
        "api-gateway": {
            "cwd": r"S:\services\api-gateway",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7000"],
        },
        "model-router": {
            "cwd": r"S:\services\model-router",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7010"],
        },
        "memory-engine": {
            "cwd": r"S:\services\memory-engine",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7020"],
        },
        "pipecat": {
            "cwd": r"S:\services\pipecat",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7030"],
        },
        "openclaw": {
            "cwd": r"S:\services\openclaw",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7040"],
        },
        "orchestrator": {
            "cwd": r"S:\services\orchestrator",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        },
        "vision-capture": {
            "cwd": r"S:\services\vision-capture",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7060"],
        },
        "perception": {
            "cwd": r"S:\services\perception",
            "cmd": [r"S:\envs\sonia-core\python.exe", "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "7070"],
        },
    }

    # Restart policy: max restarts per window, exponential backoff
    MAX_RESTARTS = 3
    RESTART_WINDOW_S = 300.0  # 5 minutes
    BACKOFF_BASE_S = 2.0  # 2s, 4s, 8s

    async def restart_service(self, name: str) -> Dict[str, Any]:
        """
        Restart a service via subprocess.

        Enforces restart policy: max 3 restarts per 5-minute window,
        exponential backoff (2s, 4s, 8s). After exhaustion, marks UNREACHABLE.

        Returns:
            Dict with restart result including status and details.
        """
        record = self._services.get(name)
        if not record:
            raise ValueError(f"Unknown service: {name}")

        svc_cmd = self.SERVICE_COMMANDS.get(name)
        if not svc_cmd:
            return {"ok": False, "service": name, "error": f"No restart command for {name}"}

        # Check restart policy
        now = time.time()
        restart_history = getattr(record, '_restart_history', [])
        # Prune old entries outside window
        restart_history = [t for t in restart_history if now - t < self.RESTART_WINDOW_S]

        if len(restart_history) >= self.MAX_RESTARTS:
            record.state = ServiceState.UNREACHABLE
            self._emit_event("supervision.restart.exhausted", name, {
                "restart_count": len(restart_history),
                "window_s": self.RESTART_WINDOW_S,
            })
            logger.warning("Restart policy exhausted for %s (%d in %ds)",
                          name, len(restart_history), self.RESTART_WINDOW_S)
            return {
                "ok": False, "service": name,
                "error": "Restart policy exhausted",
                "restart_count": len(restart_history),
            }

        # Exponential backoff
        attempt = len(restart_history)
        backoff_s = self.BACKOFF_BASE_S * (2 ** attempt)
        if attempt > 0:
            logger.info("Restart backoff for %s: %.1fs", name, backoff_s)
            await asyncio.sleep(backoff_s)

        # Execute restart
        try:
            logger.info("Restarting service %s (attempt %d/%d)", name, attempt + 1, self.MAX_RESTARTS)

            process = subprocess.Popen(
                svc_cmd["cmd"],
                cwd=svc_cmd["cwd"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
            )

            # Record restart
            restart_history.append(now)
            record._restart_history = restart_history
            record.state = ServiceState.RECOVERING
            record.consecutive_failures = 0

            self._emit_event("supervision.service.restarted", name, {
                "pid": process.pid,
                "attempt": attempt + 1,
                "backoff_s": backoff_s,
            })

            return {
                "ok": True, "service": name,
                "pid": process.pid,
                "attempt": attempt + 1,
                "backoff_s": backoff_s,
            }

        except Exception as e:
            logger.error("Restart failed for %s: %s", name, e)
            self._emit_event("supervision.restart.failed", name, {"error": str(e)})
            return {"ok": False, "service": name, "error": str(e)}

    async def probe_all(self) -> Dict[str, ServiceRecord]:
        """Probe all services concurrently."""
        tasks = [self.probe_service(name) for name in self._services]
        await asyncio.gather(*tasks, return_exceptions=True)
        return dict(self._services)

    async def start_polling(self):
        """Start background polling loop."""
        if self._poll_task is not None:
            return
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Supervision polling started (interval=%ss)", self._poll_interval)

    async def stop_polling(self):
        """Stop background polling loop."""
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
            logger.info("Supervision polling stopped")

    async def _poll_loop(self):
        """Background health polling loop."""
        while True:
            try:
                await self.probe_all()
            except Exception as e:
                logger.error("Supervision poll error: %s", e)
            await asyncio.sleep(self._poll_interval)

    # ── Query Methods ─────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current supervision status for all services."""
        return {
            "services": {
                name: record.to_dict() for name, record in self._services.items()
            },
            "maintenance_mode": self._maintenance_mode,
            "uptime_seconds": round(time.time() - self._started_at, 1),
        }

    def get_service_state(self, name: str) -> Optional[ServiceState]:
        """Get current state of a specific service."""
        record = self._services.get(name)
        return record.state if record else None

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """Return the service dependency graph."""
        return dict(DEPENDENCY_GRAPH)

    def set_maintenance_mode(self, enabled: bool) -> Dict[str, Any]:
        """Toggle maintenance mode."""
        old = self._maintenance_mode
        self._maintenance_mode = enabled
        self._emit_event("supervision.maintenance.toggled", "eva-os", {
            "old": old,
            "new": enabled,
        })
        return {"maintenance_mode": enabled, "previous": old}

    @property
    def maintenance_mode(self) -> bool:
        return self._maintenance_mode

    @property
    def services(self) -> Dict[str, ServiceRecord]:
        return dict(self._services)
