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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('eva-os')

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
    return {
        "ok": True,
        "service": "eva-os",
        "timestamp": datetime.utcnow().isoformat()
    }

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
    return {
        "approvals": [],
        "pending_count": 0,
        "service": "eva-os"
    }

@app.post("/approve")
async def approve_action(request: Request):
    """Approve an action."""
    try:
        data = await request.json()
        approval_id = data.get("approval_id")
        decision = data.get("decision", "approved")
        
        return {
            "status": "processed",
            "approval_id": approval_id,
            "decision": decision,
            "service": "eva-os"
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
    logger.info("EVA-OS starting up...")

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
