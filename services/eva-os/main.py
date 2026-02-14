"""
Sonia EVA-OS - Main Entry Point

EVA-OS is the supervisory control plane:
  - Active service health monitoring via /healthz probes
  - Per-service state machine (healthy/degraded/unreachable/recovering)
  - Policy gating and approval workflows (via SafeOrchestrator)
  - Dependency graph awareness
  - Maintenance mode toggle
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Canonical version
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('eva-os')

# ── Safety layer import ───────────────────────────────────────────
# Add openclaw to sys.path so we can import its app package
_openclaw_root = str(Path(__file__).resolve().parent.parent / "openclaw")
if _openclaw_root not in sys.path:
    sys.path.insert(0, _openclaw_root)

# Lazy-init: populated at startup
_safe_orchestrator = None
_supervisor = None

# Create FastAPI app
app = FastAPI(
    title="Sonia EVA-OS",
    description="Supervisory control plane and orchestration",
    version=SONIA_VERSION
)

# ─────────────────────────────────────────────────────────────────────────────
# Health & Status Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Health check endpoint."""
    health = {
        "ok": True,
        "service": "eva-os",
        "timestamp": datetime.utcnow().isoformat(),
    }
    if _safe_orchestrator is not None:
        health["safety"] = _safe_orchestrator.safety_status()
    if _supervisor is not None:
        health["supervision"] = {
            "maintenance_mode": _supervisor.maintenance_mode,
            "services_tracked": len(_supervisor.services),
        }
    return health

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "eva-os",
        "status": "online",
        "version": "1.0.0"
    }

@app.get("/status")
def status():
    """Real-time status from active supervision probes."""
    if _supervisor is None:
        return {
            "service": "eva-os",
            "status": "online",
            "operational_mode": "normal",
            "uptime_seconds": 0,
            "services": {},
            "note": "supervisor not initialized",
        }

    sup_status = _supervisor.get_status()
    return {
        "service": "eva-os",
        "status": "online",
        "operational_mode": "maintenance" if _supervisor.maintenance_mode else "normal",
        "uptime_seconds": sup_status["uptime_seconds"],
        "maintenance_mode": sup_status["maintenance_mode"],
        "services": sup_status["services"],
    }

# ─────────────────────────────────────────────────────────────────────────────
# Action Safety Gate
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/gate-tool-call")
async def gate_tool_call(request: Request):
    """
    Evaluate a tool call against the action safety policy.

    Request body:
        { "tool_name": "...", "args": {...}, "id": "...",
          "approval_token": "ctk_..." (optional) }

    Returns:
        { "status": "approved" | "approval_required" | "denied", ... }
    """
    if _safe_orchestrator is None:
        raise HTTPException(status_code=503, detail="SafeOrchestrator not initialized")
    try:
        data = await request.json()
        trace_id = data.get("trace_id", data.get("id", ""))
        context = data.get("context", {})
        result = _safe_orchestrator.gate_tool_call(data, context, trace_id)
        return {**result, "service": "eva-os"}
    except Exception as e:
        logger.error(f"Gate tool call error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Orchestration Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/tasks")
def list_tasks():
    """List active tasks."""
    return {
        "tasks": [],
        "count": 0,
        "service": "eva-os"
    }

@app.post("/tasks")
async def create_task(request: Request):
    """Create a new task."""
    try:
        data = await request.json()
        task_name = data.get("name", "unnamed")

        return {
            "status": "created",
            "task_id": "task_001",
            "name": task_name,
            "service": "eva-os"
        }
    except Exception as e:
        logger.error(f"Task creation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Approval Workflow Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/approvals")
def list_approvals():
    """List pending approvals."""
    if _safe_orchestrator is not None:
        pending = _safe_orchestrator.pending_approvals()
        return {
            "approvals": pending,
            "pending_count": len(pending),
            "service": "eva-os",
        }
    return {
        "approvals": [],
        "pending_count": 0,
        "service": "eva-os",
    }

@app.post("/approve")
async def approve_action(request: Request):
    """Approve or deny a pending confirmation token."""
    try:
        data = await request.json()
        token_id = data.get("token_id") or data.get("approval_id", "")
        decision = data.get("decision", "approved")
        trace_id = data.get("trace_id", "")
        reason = data.get("reason", "User denied")

        if _safe_orchestrator is not None and token_id:
            if decision == "denied":
                result = _safe_orchestrator.deny_pending_approval(
                    token_id, trace_id=trace_id, reason=reason,
                )
            else:
                result = {
                    "status": "acknowledged",
                    "token_id": token_id,
                    "decision": decision,
                    "note": "Resubmit tool call with approval_token to proceed",
                }
            return {**result, "service": "eva-os"}

        return {
            "status": "processed",
            "approval_id": token_id,
            "decision": decision,
            "service": "eva-os",
        }
    except Exception as e:
        logger.error(f"Approval error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Supervision Endpoints (v2.9 -- real probes, no hardcoded data)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health/all")
async def health_all():
    """Probe all downstream services and return real health data."""
    if _supervisor is None:
        raise HTTPException(status_code=503, detail="Supervisor not initialized")

    await _supervisor.probe_all()
    sup = _supervisor.get_status()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "maintenance_mode": sup["maintenance_mode"],
        "services": sup["services"],
    }

@app.get("/v1/supervision/dependency-graph")
def get_dependency_graph():
    """Return the typed service dependency graph."""
    if _supervisor is None:
        raise HTTPException(status_code=503, detail="Supervisor not initialized")
    return {
        "graph": _supervisor.get_dependency_graph(),
        "service": "eva-os",
    }

@app.post("/v1/supervision/maintenance-mode")
async def toggle_maintenance(request: Request):
    """Toggle maintenance mode."""
    if _supervisor is None:
        raise HTTPException(status_code=503, detail="Supervisor not initialized")
    try:
        data = await request.json()
        enabled = data.get("enabled", False)
        result = _supervisor.set_maintenance_mode(enabled)
        return {**result, "service": "eva-os"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/v1/supervision/probe/{service_name}")
async def probe_service(service_name: str):
    """Manually probe a specific service."""
    if _supervisor is None:
        raise HTTPException(status_code=503, detail="Supervisor not initialized")
    try:
        record = await _supervisor.probe_service(service_name)
        return {**record.to_dict(), "service": "eva-os"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": str(exc),
            "service": "eva-os"
        }
    )

# ─────────────────────────────────────────────────────────────────────────────
# Startup & Shutdown
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(a):
    """Startup and shutdown lifecycle for EVA-OS."""
    global _safe_orchestrator, _supervisor
    logger.info("EVA-OS starting up...")

    # 1. Initialize SafeOrchestrator (policy gating via OpenClaw)
    try:
        import importlib.util
        _orch_path = str(Path(__file__).resolve().parent / "app" / "orchestrator.py")
        _spec = importlib.util.spec_from_file_location("safe_orchestrator", _orch_path)
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["safe_orchestrator"] = _mod
        _spec.loader.exec_module(_mod)
        _safe_orchestrator = _mod.SafeOrchestrator()
        logger.info("EVA-OS: SafeOrchestrator initialized")
    except Exception as e:
        logger.error("EVA-OS: SafeOrchestrator init failed: %s", e)
        _safe_orchestrator = None

    # 2. Initialize ServiceSupervisor (active health probing)
    try:
        from service_supervisor import ServiceSupervisor
        _supervisor = ServiceSupervisor()
        await _supervisor.start_polling()
        logger.info("EVA-OS: ServiceSupervisor initialized, polling started")
    except Exception as e:
        logger.error("EVA-OS: ServiceSupervisor init failed: %s", e)
        _supervisor = None

    yield  # ── app is running ──

    logger.info("EVA-OS shutting down...")
    if _supervisor is not None:
        await _supervisor.stop_polling()


app.router.lifespan_context = _lifespan

# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting EVA-OS on http://127.0.0.1:7050")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=7050,
        reload=False,
        log_level="info"
    )
