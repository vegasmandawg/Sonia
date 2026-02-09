"""
API Gateway Main Service
FastAPI application that orchestrates requests to Memory Engine, Model Router, OpenClaw, and Pipecat.
"""

import json
import sys
import uuid
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Optional

from clients.memory_client import MemoryClient, MemoryClientError
from clients.router_client import RouterClient, RouterClientError
from clients.openclaw_client import OpenclawClient, OpenclawClientError
from routes.chat import handle_chat
from routes.action import handle_action
from routes.turn import handle_turn
from routes.sessions import handle_create_session, handle_get_session, handle_delete_session
from routes.stream import handle_stream
from schemas.turn import TurnRequest
from schemas.session import SessionCreateRequest, ConfirmationDecisionRequest
from schemas.action import ActionPlanRequest, ActionPlanResponse, ActionStatusResponse, ActionQueueResponse
from session_manager import SessionManager
from tool_policy import GatewayConfirmationManager
from action_pipeline import ActionPipeline
from capability_registry import get_capability_registry
from circuit_breaker import get_breaker_registry
from dead_letter import get_dead_letter_queue
from health_supervisor import get_health_supervisor
from action_audit import get_audit_logger
from jsonl_logger import session_log, error_log

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

# Stage 3: session + confirmation managers
session_mgr = SessionManager()
confirmation_mgr = GatewayConfirmationManager()

# Stage 5: action pipeline (initialized on startup when openclaw_client is ready)
action_pipeline: Optional[ActionPipeline] = None

# Stage 5 M2: recovery subsystems
health_supervisor = None


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
    global memory_client, router_client, openclaw_client, action_pipeline, health_supervisor

    memory_client = MemoryClient(base_url="http://127.0.0.1:7020")
    router_client = RouterClient(base_url="http://127.0.0.1:7010")
    openclaw_client = OpenclawClient(base_url="http://127.0.0.1:7040")

    # Stage 5 M2: initialize recovery subsystems
    breaker_registry = get_breaker_registry()
    dead_letter_queue = get_dead_letter_queue()
    action_pipeline = ActionPipeline(openclaw_client, breaker_registry, dead_letter_queue)

    # Start health supervisor background loop
    health_supervisor = get_health_supervisor()
    await health_supervisor.start()

    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "event": "startup",
        "message": "API Gateway initialized with downstream clients and recovery subsystems"
    })


@app.on_event("shutdown")
async def shutdown_event():
    """Close clients and log shutdown."""
    global memory_client, router_client, openclaw_client, health_supervisor

    # Stop health supervisor
    if health_supervisor:
        await health_supervisor.stop()

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
# Stage 2 — Service-Specific Endpoints (UNCHANGED)
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


@app.post("/v1/turn")
async def turn_endpoint(request: Request, body: TurnRequest):
    """
    Full end-to-end turn pipeline.

    Accepts a JSON body with user_id, conversation_id, input_text, and optional
    profile/metadata.  Orchestrates memory recall → model generation →
    optional tool execution → memory write and returns a structured response.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())

    response = await handle_turn(
        request=body,
        memory_client=memory_client,
        router_client=router_client,
        openclaw_client=openclaw_client,
        correlation_id=correlation_id,
    )

    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "turn",
        "turn_id": response.turn_id,
        "correlation_id": correlation_id,
        "ok": response.ok,
        "duration_ms": round(response.duration_ms, 1),
    })

    result = response.dict(exclude_none=True)
    # Merge Stage 4 quality annotations and latency breakdown if present
    extra = getattr(response, "_extra_fields", None)
    if extra:
        result.update(extra)
    return result


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
# Stage 3 — Session Control Plane
# ============================================================================

@app.post("/v1/sessions")
async def create_session_endpoint(request: Request, body: SessionCreateRequest):
    """Create a new session."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    return await handle_create_session(
        user_id=body.user_id,
        conversation_id=body.conversation_id,
        profile=body.profile,
        metadata=body.metadata or {},
        session_mgr=session_mgr,
        correlation_id=correlation_id,
    )


@app.get("/v1/sessions/{session_id}")
async def get_session_endpoint(session_id: str):
    """Retrieve session info."""
    return await handle_get_session(session_id, session_mgr)


@app.delete("/v1/sessions/{session_id}")
async def delete_session_endpoint(request: Request, session_id: str):
    """Close a session."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    return await handle_delete_session(session_id, session_mgr, correlation_id)


# ============================================================================
# Stage 3 — WebSocket Stream
# ============================================================================

@app.websocket("/v1/stream/{session_id}")
async def stream_endpoint(websocket: WebSocket, session_id: str):
    """Bidirectional streaming via WebSocket with text fallback."""
    await websocket.accept()
    try:
        await handle_stream(
            websocket=websocket,
            session_id=session_id,
            session_mgr=session_mgr,
            memory_client=memory_client,
            router_client=router_client,
            openclaw_client=openclaw_client,
            confirmation_mgr=confirmation_mgr,
        )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ============================================================================
# Stage 3 — Confirmation Queue
# ============================================================================

@app.get("/v1/confirmations/pending")
async def pending_confirmations(session_id: str):
    """List pending confirmations for a session."""
    tokens = await confirmation_mgr.pending_for_session(session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "pending": [t.to_dict() for t in tokens],
        "count": len(tokens),
    }


@app.post("/v1/confirmations/{confirmation_id}/approve")
async def approve_confirmation(request: Request, confirmation_id: str):
    """Approve a pending confirmation and execute the tool."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await confirmation_mgr.approve(confirmation_id)
    if result.get("ok"):
        # Execute the tool now
        token = result.get("token")
        if token:
            try:
                exec_resp = await openclaw_client.execute(
                    tool_name=token.tool_name,
                    args=token.args,
                    timeout_ms=5000,
                    correlation_id=correlation_id,
                )
                return {
                    "ok": True,
                    "confirmation_id": confirmation_id,
                    "status": "approved",
                    "reason": "Approved and executed",
                    "tool_result": {
                        "tool_name": token.tool_name,
                        "status": exec_resp.get("status", "unknown"),
                        "result": exec_resp.get("result", {}),
                    },
                }
            except OpenclawClientError as exc:
                return {
                    "ok": False,
                    "confirmation_id": confirmation_id,
                    "status": "approved",
                    "reason": "Approved but execution failed",
                    "error": {"code": exc.code, "message": exc.message},
                }
    return {
        "ok": result.get("ok", False),
        "confirmation_id": confirmation_id,
        "status": result.get("status", "unknown"),
        "reason": result.get("reason", ""),
    }


@app.post("/v1/confirmations/{confirmation_id}/deny")
async def deny_confirmation(
    confirmation_id: str,
    body: Optional[ConfirmationDecisionRequest] = None,
):
    """Deny a pending confirmation."""
    reason = body.reason if body and body.reason else "User denied"
    result = await confirmation_mgr.deny(confirmation_id, reason=reason)
    return {
        "ok": False,
        "confirmation_id": confirmation_id,
        "status": result.get("status", "denied"),
        "reason": result.get("reason", reason),
    }


# ============================================================================
# Stage 5 — Action Pipeline
# ============================================================================

@app.post("/v1/actions/plan")
async def plan_action_endpoint(request: Request, body: ActionPlanRequest):
    """
    Plan and optionally execute a desktop action.
    dry_run=true → validate only; safe actions execute immediately;
    guarded actions go to pending_approval state.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.run(body, correlation_id)

    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "action.plan",
        "action_id": result.action_id,
        "intent": result.intent,
        "state": result.state,
        "ok": result.ok,
        "correlation_id": correlation_id,
    })

    return result.dict(exclude_none=True)


@app.get("/v1/actions/{action_id}")
async def get_action_endpoint(action_id: str):
    """Get the current state of an action."""
    record = await action_pipeline.store.get(action_id)
    if not record:
        return JSONResponse(status_code=404, content={
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": f"Action {action_id} not found"},
        })
    return {"ok": True, "action": record.dict(exclude_none=True)}


@app.post("/v1/actions/{action_id}/approve")
async def approve_action_endpoint(request: Request, action_id: str):
    """Approve a pending action and trigger execution."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.approve(action_id)

    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "action.approve",
        "action_id": action_id,
        "state": result.state,
        "ok": result.ok,
        "correlation_id": correlation_id,
    })

    return result.dict(exclude_none=True)


@app.post("/v1/actions/{action_id}/deny")
async def deny_action_endpoint(request: Request, action_id: str):
    """Deny a pending action."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.deny(action_id)

    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "action.deny",
        "action_id": action_id,
        "state": result.state,
        "ok": result.ok,
        "correlation_id": correlation_id,
    })

    return result.dict(exclude_none=True)


@app.get("/v1/actions")
async def list_actions_endpoint(
    state: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List actions with optional filters."""
    actions = await action_pipeline.store.list_actions(
        state=state, session_id=session_id, limit=limit, offset=offset
    )
    total = await action_pipeline.store.count(state=state)
    return {
        "ok": True,
        "actions": [a.dict(exclude_none=True) for a in actions],
        "total": total,
        "filters": {"state": state, "session_id": session_id, "limit": limit, "offset": offset},
    }


@app.get("/v1/capabilities")
async def capabilities_endpoint():
    """List all registered action capabilities."""
    reg = get_capability_registry()
    caps = reg.list_all()
    return {
        "ok": True,
        "capabilities": [
            {
                "intent": c.intent,
                "display_name": c.display_name,
                "description": c.description,
                "risk_level": c.risk_level,
                "requires_confirmation": c.requires_confirmation,
                "implemented": c.implemented,
                "required_params": c.required_params,
                "optional_params": c.optional_params,
                "idempotent": c.idempotent,
                "reversible": c.reversible,
                "tags": list(c.tags),
            }
            for c in caps
        ],
        "stats": reg.stats(),
    }


# ============================================================================
# Stage 5 M2 — Recovery & Observability
# ============================================================================

@app.get("/v1/health/summary")
async def health_summary_endpoint():
    """Get health supervisor summary with per-dependency states."""
    if not health_supervisor:
        return {"ok": False, "error": "Health supervisor not initialized"}
    return {"ok": True, **health_supervisor.summary()}


@app.get("/v1/breakers")
async def breakers_endpoint():
    """Get circuit breaker states for all dependencies."""
    reg = get_breaker_registry()
    return {
        "ok": True,
        "breakers": reg.summary(),
    }


@app.post("/v1/breakers/{name}/reset")
async def reset_breaker_endpoint(name: str):
    """Manually reset a circuit breaker to CLOSED state."""
    reg = get_breaker_registry()
    breaker = reg.get(name)
    if not breaker:
        return JSONResponse(status_code=404, content={
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": f"Breaker '{name}' not found"},
        })
    await breaker.reset()
    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "breaker.reset",
        "breaker": name,
    })
    return {"ok": True, "breaker": breaker.to_dict()}


@app.get("/v1/breakers/metrics")
async def breaker_metrics_endpoint(last_n: int = 50):
    """Export time-series breaker metrics for operator dashboards."""
    reg = get_breaker_registry()
    return {
        "ok": True,
        "metrics": reg.metrics(last_n=last_n),
    }


@app.get("/v1/dead-letters")
async def list_dead_letters_endpoint(
    limit: int = 50,
    offset: int = 0,
    include_replayed: bool = False,
):
    """List dead letters with optional filters."""
    dlq = get_dead_letter_queue()
    letters = await dlq.list_letters(limit=limit, offset=offset,
                                      include_replayed=include_replayed)
    total = await dlq.count(include_replayed=include_replayed)
    return {
        "ok": True,
        "dead_letters": [l.to_dict() for l in letters],
        "total": total,
    }


@app.get("/v1/dead-letters/{letter_id}")
async def get_dead_letter_endpoint(letter_id: str):
    """Get a single dead letter by ID."""
    dlq = get_dead_letter_queue()
    dl = await dlq.get(letter_id)
    if not dl:
        return JSONResponse(status_code=404, content={
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": f"Dead letter {letter_id} not found"},
        })
    return {"ok": True, "dead_letter": dl.to_dict()}


@app.post("/v1/dead-letters/{letter_id}/replay")
async def replay_dead_letter_endpoint(
    request: Request,
    letter_id: str,
    dry_run: bool = False,
):
    """
    Replay a dead-lettered action through the pipeline.
    dry_run=true → validate only, return diff without executing.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.replay_dead_letter(letter_id, dry_run=dry_run)

    log_event({
        "level": "INFO",
        "service": "api-gateway",
        "operation": "dead_letter.replay",
        "letter_id": letter_id,
        "action_id": result.action_id,
        "state": result.state,
        "ok": result.ok,
        "dry_run": dry_run,
        "correlation_id": correlation_id,
    })

    return result.dict(exclude_none=True)


@app.get("/v1/audit-trails")
async def list_audit_trails_endpoint(limit: int = 50, offset: int = 0):
    """List recent action audit trails."""
    audit = get_audit_logger()
    trails = audit.list_trails(limit=limit, offset=offset)
    return {
        "ok": True,
        "trails": trails,
        "total": audit.count(),
    }


@app.get("/v1/audit-trails/{action_id}")
async def get_audit_trail_endpoint(action_id: str):
    """Get the audit trail for a specific action."""
    audit = get_audit_logger()
    trail = audit.get_trail(action_id)
    if not trail:
        return JSONResponse(status_code=404, content={
            "ok": False,
            "error": {"code": "NOT_FOUND", "message": f"Audit trail for {action_id} not found"},
        })
    return {"ok": True, "trail": trail.to_dict()}


# ============================================================================
# Stage 7 — Diagnostic Snapshot
# ============================================================================

@app.get("/v1/diagnostics/snapshot")
async def diagnostics_snapshot_endpoint(last_n: int = 50):
    """
    Stage 7: Export a diagnostic snapshot for incident analysis.
    Returns health, breakers, DLQ, recent actions, and config metadata
    in a single response for operational debugging.
    """
    correlation_id = generate_correlation_id()
    snapshot = {"ok": True, "correlation_id": correlation_id, "timestamp": datetime.utcnow().isoformat() + "Z"}

    # Health
    try:
        if health_supervisor:
            snapshot["health"] = health_supervisor.summary()
    except Exception as e:
        snapshot["health"] = {"error": str(e)}

    # Breakers
    try:
        reg = get_breaker_registry()
        snapshot["breakers"] = reg.summary()
        snapshot["breaker_metrics"] = reg.metrics(last_n=last_n)
    except Exception as e:
        snapshot["breakers"] = {"error": str(e)}

    # DLQ
    try:
        dlq = get_dead_letter_queue()
        count = await dlq.count(include_replayed=False)
        recent = await dlq.list_letters(limit=last_n, include_replayed=False)
        snapshot["dead_letters"] = {"unresolved": count, "recent": [l.to_dict() for l in recent]}
    except Exception as e:
        snapshot["dead_letters"] = {"error": str(e)}

    # Recent actions
    try:
        if action_pipeline:
            actions = await action_pipeline.store.list_actions(limit=last_n)
            snapshot["recent_actions"] = {"count": len(actions), "actions": [a.dict(exclude_none=True) for a in actions]}
    except Exception as e:
        snapshot["recent_actions"] = {"error": str(e)}

    return snapshot


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
