"""
OpenClaw Main Service
FastAPI application with executor registry and strict safety enforcement.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from datetime import datetime
import json
import sys

OPENCLAW_DIR = Path(__file__).resolve().parent
SERVICES_DIR = OPENCLAW_DIR.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

# Canonical version
sys.path.insert(0, str(SERVICES_DIR / "shared"))
from version import SONIA_VERSION, SONIA_CONTRACT
try:
    from log_redaction import redact_string
except ImportError:
    redact_string = lambda x: x

from openclaw.schemas import (
    ExecuteRequest, ExecuteResponse, HealthzResponse, StatusResponse,
    RegistryStats
)
from openclaw.registry import get_registry

# ============================================================================
# FastAPI Application Setup
# ============================================================================

# Initialize registry on startup
registry = None


@asynccontextmanager
async def _lifespan(a):
    """Startup and shutdown lifecycle for OpenClaw."""
    global registry
    registry = get_registry()

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": "INFO",
        "service": "openclaw",
        "event": "startup",
        "tools_registered": len(registry.tools),
        "tools_implemented": len(registry.tools)
    }
    print(json.dumps(log_entry))

    yield  # ── app is running ──

    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": "INFO",
        "service": "openclaw",
        "event": "shutdown"
    }
    print(json.dumps(log_entry))


app = FastAPI(
    title="OpenClaw",
    description="Deterministic executor registry with strict safety boundaries",
    version=SONIA_VERSION,
    lifespan=_lifespan,
)


# ============================================================================
# Universal Endpoints (Contract Required)
# ============================================================================

@app.get("/healthz")
async def healthz() -> HealthzResponse:
    """
    Universal health check endpoint.
    Must respond within 2 seconds.
    """
    stats = registry.get_stats()
    return HealthzResponse(
        ok=True,
        service="openclaw",
        contract_version=SONIA_CONTRACT,
        tools_registered=stats.total_tools,
        tools_implemented=stats.implemented_tools
    )


@app.get("/version")
async def version():
    """Version endpoint."""
    return {
        "ok": True,
        "service": "openclaw",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
        "python_version": sys.version.split()[0],
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "openclaw",
        "status": "online",
        "version": SONIA_VERSION
    }


@app.get("/status")
async def status() -> StatusResponse:
    """Status endpoint with detailed information."""
    stats = registry.get_stats()
    return StatusResponse(
        service="openclaw",
        status="online",
        version=SONIA_VERSION,
        tools=stats
    )


# ============================================================================
# Service-Specific Endpoints
# ============================================================================

@app.post("/execute")
async def execute(request: ExecuteRequest) -> ExecuteResponse:
    """
    Execute a tool.
    
    Request:
    ```json
    {
        "tool_name": "shell.run",
        "args": {"command": "Get-ChildItem"},
        "timeout_ms": 5000,
        "correlation_id": "req_001"
    }
    ```
    
    Response (200 OK - Executed):
    ```json
    {
        "status": "executed",
        "tool_name": "shell.run",
        "result": {"return_code": 0, "stdout": "..."},
        "side_effects": [],
        "correlation_id": "req_001",
        "duration_ms": 45.23
    }
    ```
    
    Response (200 OK - Not Implemented):
    ```json
    {
        "status": "not_implemented",
        "tool_name": "unknown.tool",
        "message": "Tool not yet implemented",
        "correlation_id": "req_001"
    }
    ```
    
    Response (200 OK - Policy Denied):
    ```json
    {
        "status": "policy_denied",
        "tool_name": "shell.run",
        "message": "Policy denied execution",
        "error": "Command 'rm -rf /' not in allowlist",
        "correlation_id": "req_001"
    }
    ```
    """
    # Execute through registry (deterministic dispatch)
    response = registry.execute(request)
    
    # Log execution
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": "INFO",
        "service": "openclaw",
        "event": "tool_execution",
        "tool_name": request.tool_name,
        "status": response.status,
        "correlation_id": response.correlation_id,
        "duration_ms": response.duration_ms
    }
    print(json.dumps(log_entry))
    
    return response


@app.get("/tools")
async def list_tools():
    """
    List all registered tools.
    
    Response:
    ```json
    {
        "tools": [
            {
                "name": "shell.run",
                "display_name": "Shell Run",
                "description": "Execute PowerShell commands",
                "tier": "TIER_1_COMPUTE",
                "requires_sandboxing": false,
                "default_timeout_ms": 5000
            }
        ],
        "total": 4
    }
    ```
    """
    tools = registry.get_tools()
    return {
        "tools": [
            {
                "name": t.name,
                "display_name": t.display_name,
                "description": t.description,
                "tier": t.tier,
                "requires_sandboxing": t.requires_sandboxing,
                "default_timeout_ms": t.default_timeout_ms
            }
            for t in tools.values()
        ],
        "total": len(tools)
    }


@app.get("/tools/{tool_name}")
async def get_tool(tool_name: str):
    """
    Get specific tool metadata.
    
    Response:
    ```json
    {
        "name": "shell.run",
        "display_name": "Shell Run",
        "description": "Execute PowerShell commands",
        "tier": "TIER_1_COMPUTE",
        "requires_sandboxing": false,
        "default_timeout_ms": 5000,
        "allowed_by_default": true
    }
    ```
    """
    tool = registry.get_tool(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    
    return {
        "name": tool.name,
        "display_name": tool.display_name,
        "description": tool.description,
        "tier": tool.tier,
        "requires_sandboxing": tool.requires_sandboxing,
        "default_timeout_ms": tool.default_timeout_ms,
        "allowed_by_default": tool.allowed_by_default
    }


@app.get("/registry/stats")
async def registry_stats():
    """
    Get registry statistics.
    
    Response:
    ```json
    {
        "total_tools": 4,
        "implemented_tools": 4,
        "readonly_tools": 1,
        "compute_tools": 2,
        "create_tools": 1,
        "destructive_tools": 0
    }
    ```
    """
    stats = registry.get_stats()
    return {
        "total_tools": stats.total_tools,
        "implemented_tools": stats.implemented_tools,
        "readonly_tools": stats.readonly_tools,
        "compute_tools": stats.compute_tools,
        "create_tools": stats.create_tools,
        "destructive_tools": stats.destructive_tools
    }


@app.get("/breakers")
async def breaker_status():
    """Circuit breaker status for all tools."""
    try:
        from openclaw.retry import ToolRetryExecutor
        executor = ToolRetryExecutor()
        return {
            "ok": True,
            "breakers": executor.all_breaker_status(),
            "service": "openclaw",
        }
    except Exception:
        return {"ok": True, "breakers": [], "service": "openclaw"}


@app.get("/logs/execution")
async def execution_logs(limit: int = 100):
    """
    Get execution logs.
    
    Query Parameters:
    - limit: Maximum number of log entries to return (default 100)
    
    Response:
    ```json
    {
        "logs": [...],
        "total": 42
    }
    ```
    """
    logs = registry.get_execution_log()
    
    # Return limited results
    limited_logs = logs[-limit:] if limit > 0 else logs
    
    return {
        "logs": limited_logs,
        "total": len(logs),
        "returned": len(limited_logs)
    }


# ============================================================================
# Error Handling
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "service": "openclaw",
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    redacted_error = redact_string(str(exc))
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": "ERROR",
        "service": "openclaw",
        "error": redacted_error,
        "path": request.url.path
    }
    print(json.dumps(log_entry), file=sys.stderr)

    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "service": "openclaw",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error"
            }
        }
    )


# ============================================================================
# Startup Verification
# ============================================================================

if __name__ == "__main__":
    # This is just for reference - actual startup is via uvicorn
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=7040,
        reload=False
    )
