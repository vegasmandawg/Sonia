"""
API Gateway Main Service
FastAPI application that orchestrates requests to Memory Engine, Model Router, OpenClaw, and Pipecat.
"""

import json
import sys
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Optional

from clients.memory_client import MemoryClient, MemoryClientError
from clients.router_client import RouterClient, RouterClientError
from clients.openclaw_client import OpenclawClient, OpenclawClientError
from routes.chat import handle_chat
from routes.action import handle_action

# ============================================================================
# FastAPI Application Setup
# ============================================================================

app = FastAPI(
    title="API Gateway",
    description="Request orchestration to Memory Engine, Model Router, OpenClaw, and Pipecat",
    version="1.0.0"
)

# Global clients (initialized on startup)
memory_client: Optional[MemoryClient] = None
router_client: Optional[RouterClient] = None
openclaw_client: Optional[OpenclawClient] = None


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return f"req_{uuid.uuid4().hex[:12]}"


def log_event(event_dict: dict):
    """Log event as JSON line."""
    event_dict.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
    print(json.dumps(event_dict))


@app.on_event("startup")
async def startup_event():
    """Initialize clients and log startup."""
    global memory_client, router_client, openclaw_client
    
    memory_client = MemoryClient(base_url="http://127.0.0.1:7020")
    router_client = RouterClient(base_url="http://127.0.0.1:7010")
    openclaw_client = OpenclawClient(base_url="http://127.0.0.1:7040")
    
    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "event": "startup",
        "message": "API Gateway initialized with downstream clients"
    })


@app.on_event("shutdown")
async def shutdown_event():
    """Close clients and log shutdown."""
    global memory_client, router_client, openclaw_client
    
    if memory_client:
        await memory_client.close()
    if router_client:
        await router_client.close()
    if openclaw_client:
        await openclaw_client.close()
    
    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "event": "shutdown",
        "message": "API Gateway shutdown complete"
    })


# ============================================================================
# Universal Endpoints (Contract Required)
# ============================================================================

@app.get("/healthz")
async def healthz():
    """Health check endpoint (2s timeout per BOOT_CONTRACT)."""
    return {
        "ok": True,
        "service": "api-gateway",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "api-gateway",
        "status": "online",
        "version": "1.0.0"
    }


@app.get("/status")
async def status():
    """Status endpoint with detailed information."""
    return {
        "service": "api-gateway",
        "status": "online",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": "1.0.0"
    }


# ============================================================================
# Service-Specific Endpoints
# ============================================================================

@app.post("/v1/chat")
async def chat_endpoint(
    request: Request,
    message: str,
    session_id: Optional[str] = None,
    model: Optional[str] = None
):
    """
    Chat endpoint with Memory Engine context and Model Router response.
    
    Request body:
    ```json
    {
        "message": "What is the weather?",
        "session_id": "optional_session_id",
        "model": "optional_model_name"
    }
    ```
    
    Response: Standard envelope with chat response, model, provider, and provenance.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    if not message:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "service": "api-gateway",
                "operation": "chat",
                "correlation_id": correlation_id,
                "duration_ms": 0,
                "data": None,
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "message is required",
                    "details": {}
                }
            }
        )
    
    response = await handle_chat(
        message=message,
        memory_client=memory_client,
        router_client=router_client,
        session_id=session_id,
        correlation_id=correlation_id,
        model=model
    )
    
    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "chat",
        "correlation_id": correlation_id,
        "status": "ok" if response["ok"] else "failed",
        "duration_ms": response["duration_ms"]
    })
    
    return response


@app.post("/v1/action")
async def action_endpoint(
    request: Request,
    tool_name: str,
    args: Optional[dict] = None,
    timeout_ms: int = 5000
):
    """
    Action endpoint for tool execution via OpenClaw.
    
    Request body:
    ```json
    {
        "tool_name": "shell.run",
        "args": {"command": "Get-ChildItem"},
        "timeout_ms": 5000
    }
    ```
    
    Response: Standard envelope with execution result.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    if not tool_name:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "service": "api-gateway",
                "operation": "action",
                "correlation_id": correlation_id,
                "duration_ms": 0,
                "data": None,
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "tool_name is required",
                    "details": {}
                }
            }
        )
    
    response = await handle_action(
        tool_name=tool_name,
        args=args or {},
        openclaw_client=openclaw_client,
        correlation_id=correlation_id,
        timeout_ms=timeout_ms
    )
    
    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "action",
        "tool_name": tool_name,
        "correlation_id": correlation_id,
        "status": "ok" if response["ok"] else "failed",
        "duration_ms": response["duration_ms"]
    })
    
    return response


@app.get("/v1/deps")
async def deps_endpoint(request: Request):
    """
    Check connectivity to all downstream services.
    
    Response: Status of each downstream service with latency.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    deps = {
        "memory_engine": {"status": "checking"},
        "model_router": {"status": "checking"},
        "openclaw": {"status": "checking"},
        "pipecat": {"status": "checking"}
    }
    
    # Check Memory Engine
    try:
        status = await memory_client.get_status(correlation_id=correlation_id)
        deps["memory_engine"] = {
            "status": "ok",
            "port": 7020,
            "service": status.get("service")
        }
    except MemoryClientError as e:
        deps["memory_engine"] = {
            "status": "unavailable",
            "port": 7020,
            "error": e.code
        }
    
    # Check Model Router
    try:
        status = await router_client.get_status(correlation_id=correlation_id)
        deps["model_router"] = {
            "status": "ok",
            "port": 7010,
            "service": status.get("service")
        }
    except RouterClientError as e:
        deps["model_router"] = {
            "status": "unavailable",
            "port": 7010,
            "error": e.code
        }
    
    # Check OpenClaw
    try:
        status = await openclaw_client.get_status(correlation_id=correlation_id)
        deps["openclaw"] = {
            "status": "ok",
            "port": 7040,
            "service": status.get("service")
        }
    except OpenclawClientError as e:
        deps["openclaw"] = {
            "status": "unavailable",
            "port": 7040,
            "error": e.code
        }
    
    # Note: Pipecat check would go here (7030)
    # For now, marked as pending implementation
    deps["pipecat"] = {
        "status": "pending",
        "port": 7030,
        "message": "Pipecat Phase 2 - coming soon"
    }
    
    return {
        "ok": all(d.get("status") == "ok" for d in deps.values() if d.get("status") != "pending"),
        "service": "api-gateway",
        "operation": "deps",
        "correlation_id": correlation_id,
        "duration_ms": 0,
        "data": deps,
        "error": None
    }


# ============================================================================
# Error Handling
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "service": "api-gateway",
            "operation": request.url.path,
            "correlation_id": correlation_id,
            "duration_ms": 0,
            "data": None,
            "error": {
                "code": "HTTP_ERROR",
                "message": exc.detail,
                "details": {}
            }
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    log_event({
        "level": "ERROR",
        "service": "api-gateway",
        "error": str(exc),
        "error_type": type(exc).__name__,
        "path": request.url.path,
        "correlation_id": correlation_id
    })
    
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "service": "api-gateway",
            "operation": request.url.path,
            "correlation_id": correlation_id,
            "duration_ms": 0,
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error",
                "details": {}
            }
        }
    )


# ============================================================================
# Startup Verification
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=7000,
        reload=False
    )
