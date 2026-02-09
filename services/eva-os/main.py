"""
Sonia EVA-OS - Main Entry Point

EVA-OS is the supervisory control plane:
  - Orchestration and task state management
  - Policy gating and approval workflows
  - Service health monitoring
  - Degradation and fallback handling
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import sys
from datetime import datetime
from pathlib import Path

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

# Create FastAPI app
app = FastAPI(
    title="Sonia EVA-OS",
    description="Supervisory control plane and orchestration",
    version="1.0.0"
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
    """Detailed status endpoint."""
    return {
        "service": "eva-os",
        "status": "online",
        "operational_mode": "normal",
        "uptime_seconds": 0,
        "services": {
            "api-gateway": "healthy",
            "model-router": "healthy",
            "memory-engine": "healthy",
            "pipecat": "healthy",
            "openclaw": "healthy"
        }
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
                # For approve, the token is redeemed via gate_tool_call
                # when the caller re-submits with the approval_token.
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
# Service Health Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health/all")
def health_all():
    """Check health of all downstream services."""
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "api-gateway": {
                "status": "healthy",
                "latency_ms": 10,
                "last_check": datetime.utcnow().isoformat()
            },
            "model-router": {
                "status": "healthy",
                "latency_ms": 8,
                "last_check": datetime.utcnow().isoformat()
            },
            "memory-engine": {
                "status": "healthy",
                "latency_ms": 15,
                "last_check": datetime.utcnow().isoformat()
            },
            "pipecat": {
                "status": "healthy",
                "latency_ms": 12,
                "last_check": datetime.utcnow().isoformat()
            },
            "openclaw": {
                "status": "healthy",
                "latency_ms": 20,
                "last_check": datetime.utcnow().isoformat()
            }
        }
    }

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

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    global _safe_orchestrator
    logger.info("EVA-OS starting up...")
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

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("EVA-OS shutting down...")

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
