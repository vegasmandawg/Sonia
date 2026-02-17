"""
API Gateway Main Service — SONIA v3.0.0
FastAPI application that orchestrates requests to Memory Engine, Model Router, OpenClaw, and Pipecat.

v3.0.0 M1: Contract + Config Cut
  - /v3/* endpoints are canonical
  - /v1/* endpoints preserved with deprecation warnings (removal in v3.1)
  - Config schema validation on startup
"""

import json
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Optional

# Canonical version
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION, SONIA_CONTRACT

from clients.memory_client import MemoryClient, MemoryClientError
from clients.router_client import RouterClient, RouterClientError
from clients.openclaw_client import OpenclawClient, OpenclawClientError
from routes.chat import handle_chat
from routes.action import handle_action
from routes.turn import handle_turn
from routes.sessions import handle_create_session, handle_get_session, handle_delete_session
from routes.stream import handle_stream
from routes.ui_stream import handle_ui_stream, ui_stream_manager, inject_clients as inject_ui_clients
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
from state_backup import get_backup_manager
from durable_state import get_durable_state_store
from memory_policy import set_memory_policy_state_store
from jsonl_logger import session_log, error_log
from auth import AuthMiddleware

# v4.4 Epic A: TLS env vars — SONIA_TLS_CERT / SONIA_TLS_KEY passed to uvicorn ssl_certfile/ssl_keyfile

logger = logging.getLogger("api-gateway")

# ============================================================================
# FastAPI Application Setup
# ============================================================================

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


# ============================================================================
# V1 Deprecation Support
# ============================================================================

_V1_DEPRECATION = {
    "deprecated": True,
    "removal_version": "v3.1.0",
    "message": "This v1 endpoint is deprecated. Migrate to /v3/* equivalent.",
}


def _add_deprecation(result):
    """Inject _deprecation field into a v1 response dict."""
    if isinstance(result, dict):
        result["_deprecation"] = _V1_DEPRECATION
    return result


@asynccontextmanager
async def lifespan(a):
    """Startup and shutdown lifecycle for API Gateway."""
    global memory_client, router_client, openclaw_client, action_pipeline, health_supervisor

    # v3.0: Config validation on startup (best-effort, do not block boot)
    try:
        from config_validator import SoniaConfig
        cfg = SoniaConfig()
        log_event({
            "level": "INFO",
            "service": "api-gateway",
            "event": "config_validated",
            "config_schema": cfg.schema_version,
            "config_version": cfg.version,
        })
    except Exception as e:
        log_event({
            "level": "WARN",
            "service": "api-gateway",
            "event": "config_validation_skipped",
            "reason": str(e),
        })

    memory_client = MemoryClient(base_url="http://127.0.0.1:7020")
    router_client = RouterClient(base_url="http://127.0.0.1:7010")
    openclaw_client = OpenclawClient(base_url="http://127.0.0.1:7040")

    # v3.0: inject clients into UI stream handler for conversation bridge
    inject_ui_clients(memory_client, router_client, openclaw_client)

    # v4.3 Epic A: initialize durable state store (SQLite write-through)
    durable_store = get_durable_state_store()
    session_mgr.set_state_store(durable_store)
    confirmation_mgr.set_state_store(durable_store)
    dead_letter_queue_ref = get_dead_letter_queue()
    dead_letter_queue_ref.set_state_store(durable_store)
    set_memory_policy_state_store(durable_store)

    # M2: wire session manager to memory client for persistence (legacy fallback)
    session_mgr.set_memory_client(memory_client)

    # v4.3: restore all persisted state from durable store
    try:
        restore_counts = await durable_store.restore_all()
        log_event({"level": "INFO", "service": "api-gateway", "event": "durable_state_restore", "counts": restore_counts})
    except Exception as e:
        log_event({"level": "WARN", "service": "api-gateway", "event": "durable_state_restore_failed", "reason": str(e)})

    # Restore sessions (prefers durable store, falls back to memory-engine)
    try:
        restored = await session_mgr.restore_sessions()
        log_event({"level": "INFO", "service": "api-gateway", "event": "sessions_restored", "count": restored})
    except Exception as e:
        log_event({"level": "WARN", "service": "api-gateway", "event": "session_restore_failed", "reason": str(e)})

    # Restore confirmations from durable store
    try:
        cfm_restored = await confirmation_mgr.restore_confirmations()
        log_event({"level": "INFO", "service": "api-gateway", "event": "confirmations_restored", "count": cfm_restored})
    except Exception as e:
        log_event({"level": "WARN", "service": "api-gateway", "event": "confirmation_restore_failed", "reason": str(e)})

    # Restore dead letters from durable store
    try:
        dl_restored = await dead_letter_queue_ref.restore_dead_letters()
        log_event({"level": "INFO", "service": "api-gateway", "event": "dead_letters_restored", "count": dl_restored})
    except Exception as e:
        log_event({"level": "WARN", "service": "api-gateway", "event": "dead_letter_restore_failed", "reason": str(e)})

    # M2: configure auth middleware (v3.5: default-on with SONIA_DEV_MODE bypass)
    auth_cfg = {}
    try:
        from config_validator import SoniaConfig as _SC
        _c = _SC()
        auth_cfg = _c.get("auth")
    except Exception:
        pass

    import os as _os
    dev_mode = _os.environ.get("SONIA_DEV_MODE", "").strip() == "1"
    # Auth is ON by default. Only SONIA_DEV_MODE=1 disables it.
    # Config "enabled" field is ignored in v3.5+; use env var for override.
    auth_enabled = not dev_mode

    if dev_mode:
        log_event({
            "level": "WARN", "service": "api-gateway",
            "event": "auth_disabled_dev_mode",
            "message": "WARNING: Auth disabled -- SONIA_DEV_MODE=1. Do not use in production.",
            "env_var": "SONIA_DEV_MODE=1"
        })

    if auth_enabled:
        exempt = set(auth_cfg.get("exempt_paths", []))
        exempt.update({"/healthz", "/health", "/status", "/", "/docs", "/openapi.json", "/redoc",
                       "/version", "/pragmas"})
        app.add_middleware(
            AuthMiddleware,
            enabled=True,
            exempt_paths=exempt,
            service_token=auth_cfg.get("service_token", ""),
            memory_client=memory_client,
            cache_ttl=auth_cfg.get("key_cache_ttl_seconds", 300),
            cache_max=auth_cfg.get("key_cache_max_entries", 100),
        )
        log_event({"level": "INFO", "service": "api-gateway", "event": "auth_enabled", "exempt_paths": len(exempt)})
    else:
        log_event({"level": "INFO", "service": "api-gateway", "event": "auth_disabled", "reason": "SONIA_DEV_MODE=1"})

    # Store auth posture for visibility endpoints
    app.state.auth_posture = {
        "auth_enabled": auth_enabled,
        "dev_mode": dev_mode,
        "exempt_path_count": len(exempt) if auth_enabled else 0,
    }

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
        "version": SONIA_VERSION,
        "contract": SONIA_CONTRACT,
        "message": "API Gateway v3.0.0 initialized with downstream clients, auth, and recovery subsystems"
    })

    yield  # -- app is running --

    # Stop health supervisor
    if health_supervisor:
        await health_supervisor.stop()

    # v4.3: close durable state store
    try:
        durable_store.close()
    except Exception:
        pass

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


app = FastAPI(
    title="API Gateway",
    description="SONIA v3.0.0 - Request orchestration to Memory Engine, Model Router, OpenClaw, and Pipecat",
    version=SONIA_VERSION,
    lifespan=lifespan,
)

# v4.4 Epic A: CORS origins configurable via SONIA_CORS_ORIGINS env var (comma-separated)
import os as _cors_os
_default_cors = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
_cors_env = _cors_os.environ.get("SONIA_CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else _default_cors

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Deprecated", "X-Removal-Version", "X-Migrate-To"],
)

# ── Rate limiting ──
try:
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent / "shared"))
    from rate_limiter import RateLimiter
    _rate_limiter = RateLimiter(rate=20.0, burst=40)
except ImportError:
    _rate_limiter = None

# ── Log redaction ──
try:
    from log_redaction import redact_dict
except ImportError:
    redact_dict = None


# ============================================================================
# V1 Deprecation Middleware (HTTP only; WebSocket handled separately)
# ============================================================================

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Per-client rate limiting via token bucket."""
    if _rate_limiter is not None:
        client_id = request.headers.get("X-API-Key", request.client.host if request.client else "unknown")
        allowed, retry_after = _rate_limiter.check(client_id)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "ok": False,
                    "service": "api-gateway",
                    "error": {"code": "RATE_LIMITED", "message": "Too many requests", "retry_after": round(retry_after, 2)},
                },
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
    return await call_next(request)


@app.middleware("http")
async def v1_deprecation_middleware(request: Request, call_next):
    """Add deprecation headers to all /v1/* HTTP responses."""
    response = await call_next(request)
    if request.url.path.startswith("/v1/"):
        response.headers["X-Deprecated"] = "true"
        response.headers["X-Removal-Version"] = "v3.1.0"
        response.headers["X-Migrate-To"] = request.url.path.replace("/v1/", "/v3/", 1)
    return response


# ============================================================================
# Universal Endpoints (Contract Required)
# ============================================================================

@app.get("/healthz")
async def healthz():
    """Health check endpoint (2s timeout per BOOT_CONTRACT)."""
    return {
        "ok": True,
        "service": "api-gateway",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
        "baseline_contract": SONIA_CONTRACT,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/version")
async def version():
    """Version endpoint — returns version, contract, and build metadata."""
    return {
        "ok": True,
        "service": "api-gateway",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
        "python_version": sys.version.split()[0],
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "api-gateway",
        "status": "online",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
    }


@app.get("/status")
async def status():
    """Status endpoint with detailed information including auth posture."""
    posture = getattr(app.state, "auth_posture", {"auth_enabled": False, "dev_mode": True})
    return {
        "service": "api-gateway",
        "status": "online",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
        "auth_posture": posture,
    }


# ============================================================================
# Chat Endpoint (v3 canonical + v1 compat)
# ============================================================================

async def _do_chat(request: Request, message: str, session_id: Optional[str], model: Optional[str]):
    """Shared chat logic for v3 and v1."""
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


@app.post("/v3/chat")
async def v3_chat_endpoint(request: Request, message: str, session_id: Optional[str] = None, model: Optional[str] = None):
    """V3 chat endpoint with Memory Engine context and Model Router response."""
    return await _do_chat(request, message, session_id, model)


@app.post("/v1/chat")
async def v1_chat_endpoint(request: Request, message: str, session_id: Optional[str] = None, model: Optional[str] = None):
    """V1 chat endpoint (DEPRECATED - use /v3/chat)."""
    result = await _do_chat(request, message, session_id, model)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


# ============================================================================
# Turn Pipeline (v3 canonical + v1 compat)
# ============================================================================

async def _do_turn(request: Request, body: TurnRequest):
    """Shared turn pipeline logic."""
    import asyncio as _aio
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
    extra = getattr(response, "_extra_fields", None)
    if extra:
        result.update(extra)

    # M2: fire-and-forget conversation history write
    if memory_client and response.ok:
        user_id = getattr(request.state, "user_id", None) or body.session_id or "anonymous"
        turn_data = {
            "turn_id": response.turn_id,
            "session_id": body.session_id or "",
            "user_id": user_id,
            "sequence_num": result.get("turn_count", 0),
            "user_input": body.user_input,
            "assistant_response": result.get("response", ""),
            "model_used": result.get("model", ""),
            "tool_calls": result.get("tool_calls"),
            "latency_ms": response.duration_ms,
            "metadata": {
                "correlation_id": correlation_id,
                "profile": result.get("generation_profile_used"),
            },
        }
        _aio.create_task(_write_turn_history(turn_data, correlation_id))

    return result


async def _write_turn_history(turn_data: dict, correlation_id: str):
    """Best-effort conversation history persistence."""
    try:
        await memory_client.write_turn(turn_data, correlation_id=correlation_id)
    except Exception as e:
        logger.warning("History write failed for turn %s: %s", turn_data.get("turn_id"), e)


@app.post("/v3/turn")
async def v3_turn_endpoint(request: Request, body: TurnRequest):
    """V3 full end-to-end turn pipeline."""
    return await _do_turn(request, body)


@app.post("/v1/turn")
async def v1_turn_endpoint(request: Request, body: TurnRequest):
    """V1 turn pipeline (DEPRECATED - use /v3/turn)."""
    result = await _do_turn(request, body)
    return _add_deprecation(result)


# ============================================================================
# Action Endpoint (v3 canonical + v1 compat)
# ============================================================================

async def _do_action(request: Request, tool_name: str, args: Optional[dict], timeout_ms: int):
    """Shared action logic."""
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


@app.post("/v3/action")
async def v3_action_endpoint(request: Request, tool_name: str, args: Optional[dict] = None, timeout_ms: int = 5000):
    """V3 action endpoint for tool execution via OpenClaw."""
    return await _do_action(request, tool_name, args, timeout_ms)


@app.post("/v1/action")
async def v1_action_endpoint(request: Request, tool_name: str, args: Optional[dict] = None, timeout_ms: int = 5000):
    """V1 action endpoint (DEPRECATED - use /v3/action)."""
    result = await _do_action(request, tool_name, args, timeout_ms)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


# ============================================================================
# Deps Endpoint (v3 canonical + v1 compat)
# ============================================================================

async def _do_deps(request: Request):
    """Shared deps logic."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())

    deps = {
        "memory_engine": {"status": "checking"},
        "model_router": {"status": "checking"},
        "openclaw": {"status": "checking"},
        "pipecat": {"status": "checking"}
    }

    try:
        st = await memory_client.get_status(correlation_id=correlation_id)
        deps["memory_engine"] = {"status": "ok", "port": 7020, "service": st.get("service")}
    except MemoryClientError as e:
        deps["memory_engine"] = {"status": "unavailable", "port": 7020, "error": e.code}

    try:
        st = await router_client.get_status(correlation_id=correlation_id)
        deps["model_router"] = {"status": "ok", "port": 7010, "service": st.get("service")}
    except RouterClientError as e:
        deps["model_router"] = {"status": "unavailable", "port": 7010, "error": e.code}

    try:
        st = await openclaw_client.get_status(correlation_id=correlation_id)
        deps["openclaw"] = {"status": "ok", "port": 7040, "service": st.get("service")}
    except OpenclawClientError as e:
        deps["openclaw"] = {"status": "unavailable", "port": 7040, "error": e.code}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://127.0.0.1:7030/healthz")
            resp.raise_for_status()
            pipecat_data = resp.json()
            deps["pipecat"] = {"status": "ok", "port": 7030, "service": pipecat_data.get("service")}
    except Exception:
        deps["pipecat"] = {"status": "unavailable", "port": 7030, "error": "HEALTH_CHECK_FAILED"}

    return {
        "ok": all(d.get("status") == "ok" for d in deps.values() if d.get("status") != "pending"),
        "service": "api-gateway",
        "operation": "deps",
        "correlation_id": correlation_id,
        "duration_ms": 0,
        "data": deps,
        "error": None
    }


@app.get("/v3/deps")
async def v3_deps_endpoint(request: Request):
    """V3 dependency check endpoint."""
    return await _do_deps(request)


@app.get("/v1/deps")
async def v1_deps_endpoint(request: Request):
    """V1 deps endpoint (DEPRECATED - use /v3/deps)."""
    result = await _do_deps(request)
    return _add_deprecation(result)


# ============================================================================
# Session Control Plane (v3 canonical + v1 compat)
# ============================================================================

@app.post("/v3/sessions")
async def v3_create_session_endpoint(request: Request, body: SessionCreateRequest):
    """V3 create session."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    return await handle_create_session(
        user_id=body.user_id, conversation_id=body.conversation_id,
        profile=body.profile, metadata=body.metadata or {},
        session_mgr=session_mgr, correlation_id=correlation_id,
    )


@app.post("/v1/sessions")
async def v1_create_session_endpoint(request: Request, body: SessionCreateRequest):
    """V1 create session (DEPRECATED - use /v3/sessions)."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await handle_create_session(
        user_id=body.user_id, conversation_id=body.conversation_id,
        profile=body.profile, metadata=body.metadata or {},
        session_mgr=session_mgr, correlation_id=correlation_id,
    )
    return _add_deprecation(result)


@app.get("/v3/sessions/{session_id}")
async def v3_get_session_endpoint(session_id: str):
    """V3 get session."""
    return await handle_get_session(session_id, session_mgr)


@app.get("/v1/sessions/{session_id}")
async def v1_get_session_endpoint(session_id: str):
    """V1 get session (DEPRECATED)."""
    result = await handle_get_session(session_id, session_mgr)
    return _add_deprecation(result)


@app.delete("/v3/sessions/{session_id}")
async def v3_delete_session_endpoint(request: Request, session_id: str):
    """V3 delete session."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    return await handle_delete_session(session_id, session_mgr, correlation_id)


@app.delete("/v1/sessions/{session_id}")
async def v1_delete_session_endpoint(request: Request, session_id: str):
    """V1 delete session (DEPRECATED)."""
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await handle_delete_session(session_id, session_mgr, correlation_id)
    return _add_deprecation(result)


# ============================================================================
# WebSocket Stream (v3 canonical + v1 compat)
# ============================================================================

async def _do_stream(websocket: WebSocket, session_id: str):
    """Shared WebSocket stream logic."""
    await websocket.accept()
    try:
        await handle_stream(
            websocket=websocket, session_id=session_id,
            session_mgr=session_mgr, memory_client=memory_client,
            router_client=router_client, openclaw_client=openclaw_client,
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


@app.websocket("/v3/stream/{session_id}")
async def v3_stream_endpoint(websocket: WebSocket, session_id: str):
    """V3 bidirectional streaming via WebSocket."""
    await _do_stream(websocket, session_id)


@app.websocket("/v1/stream/{session_id}")
async def v1_stream_endpoint(websocket: WebSocket, session_id: str):
    """V1 stream (DEPRECATED - use /v3/stream)."""
    await _do_stream(websocket, session_id)


# ============================================================================
# UI Stream (v3 canonical + v1 compat)
# ============================================================================

async def _do_ui_stream(websocket: WebSocket):
    """Shared UI stream logic."""
    await websocket.accept()
    session_id = f"ui-{uuid.uuid4().hex[:8]}"
    correlation_id = generate_correlation_id()
    try:
        await handle_ui_stream(
            websocket=websocket, session_id=session_id, correlation_id=correlation_id,
        )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.websocket("/v3/ui/stream")
async def v3_ui_stream_endpoint(websocket: WebSocket):
    """V3 UI console WebSocket for control ACK round-trips."""
    await _do_ui_stream(websocket)


@app.websocket("/v1/ui/stream")
async def v1_ui_stream_endpoint(websocket: WebSocket):
    """V1 UI stream (DEPRECATED - use /v3/ui/stream)."""
    await _do_ui_stream(websocket)


# ============================================================================
# Confirmation Queue (v3 canonical + v1 compat)
# ============================================================================

async def _do_pending_confirmations(session_id: str):
    tokens = await confirmation_mgr.pending_for_session(session_id)
    return {
        "ok": True,
        "session_id": session_id,
        "pending": [t.to_dict() for t in tokens],
        "count": len(tokens),
    }


@app.get("/v3/confirmations/pending")
async def v3_pending_confirmations(session_id: str):
    """V3 list pending confirmations."""
    return await _do_pending_confirmations(session_id)


@app.get("/v1/confirmations/pending")
async def v1_pending_confirmations(session_id: str):
    """V1 pending confirmations (DEPRECATED)."""
    return _add_deprecation(await _do_pending_confirmations(session_id))


async def _do_approve_confirmation(request: Request, confirmation_id: str):
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await confirmation_mgr.approve(confirmation_id)
    if result.get("ok"):
        token = result.get("token")
        if token:
            try:
                exec_resp = await openclaw_client.execute(
                    tool_name=token.tool_name, args=token.args,
                    timeout_ms=5000, correlation_id=correlation_id,
                )
                return {
                    "ok": True, "confirmation_id": confirmation_id,
                    "status": "approved", "reason": "Approved and executed",
                    "tool_result": {
                        "tool_name": token.tool_name,
                        "status": exec_resp.get("status", "unknown"),
                        "result": exec_resp.get("result", {}),
                    },
                }
            except OpenclawClientError as exc:
                return {
                    "ok": False, "confirmation_id": confirmation_id,
                    "status": "approved", "reason": "Approved but execution failed",
                    "error": {"code": exc.code, "message": exc.message},
                }
    return {
        "ok": result.get("ok", False), "confirmation_id": confirmation_id,
        "status": result.get("status", "unknown"), "reason": result.get("reason", ""),
    }


@app.post("/v3/confirmations/{confirmation_id}/approve")
async def v3_approve_confirmation(request: Request, confirmation_id: str):
    """V3 approve confirmation."""
    return await _do_approve_confirmation(request, confirmation_id)


@app.post("/v1/confirmations/{confirmation_id}/approve")
async def v1_approve_confirmation(request: Request, confirmation_id: str):
    """V1 approve confirmation (DEPRECATED)."""
    return _add_deprecation(await _do_approve_confirmation(request, confirmation_id))


async def _do_deny_confirmation(confirmation_id: str, body: Optional[ConfirmationDecisionRequest]):
    reason = body.reason if body and body.reason else "User denied"
    result = await confirmation_mgr.deny(confirmation_id, reason=reason)
    return {
        "ok": False, "confirmation_id": confirmation_id,
        "status": result.get("status", "denied"), "reason": result.get("reason", reason),
    }


@app.post("/v3/confirmations/{confirmation_id}/deny")
async def v3_deny_confirmation(confirmation_id: str, body: Optional[ConfirmationDecisionRequest] = None):
    """V3 deny confirmation."""
    return await _do_deny_confirmation(confirmation_id, body)


@app.post("/v1/confirmations/{confirmation_id}/deny")
async def v1_deny_confirmation(confirmation_id: str, body: Optional[ConfirmationDecisionRequest] = None):
    """V1 deny confirmation (DEPRECATED)."""
    return _add_deprecation(await _do_deny_confirmation(confirmation_id, body))


# ============================================================================
# Action Pipeline (v3 canonical + v1 compat)
# ============================================================================

async def _do_plan_action(request: Request, body: ActionPlanRequest):
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.run(body, correlation_id)
    log_event({
        "level": "INFO", "service": "api-gateway", "operation": "action.plan",
        "action_id": result.action_id, "intent": result.intent,
        "state": result.state, "ok": result.ok, "correlation_id": correlation_id,
    })
    return result.dict(exclude_none=True)


@app.post("/v3/actions/plan")
async def v3_plan_action_endpoint(request: Request, body: ActionPlanRequest):
    """V3 plan and optionally execute a desktop action."""
    return await _do_plan_action(request, body)


@app.post("/v1/actions/plan")
async def v1_plan_action_endpoint(request: Request, body: ActionPlanRequest):
    """V1 plan action (DEPRECATED)."""
    return _add_deprecation(await _do_plan_action(request, body))


async def _do_get_action(action_id: str):
    record = await action_pipeline.store.get(action_id)
    if not record:
        return JSONResponse(status_code=404, content={
            "ok": False, "error": {"code": "NOT_FOUND", "message": f"Action {action_id} not found"},
        })
    return {"ok": True, "action": record.dict(exclude_none=True)}


@app.get("/v3/actions/{action_id}")
async def v3_get_action_endpoint(action_id: str):
    """V3 get action state."""
    return await _do_get_action(action_id)


@app.get("/v1/actions/{action_id}")
async def v1_get_action_endpoint(action_id: str):
    """V1 get action (DEPRECATED)."""
    result = await _do_get_action(action_id)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


async def _do_approve_action(request: Request, action_id: str):
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.approve(action_id)
    log_event({
        "level": "INFO", "service": "api-gateway", "operation": "action.approve",
        "action_id": action_id, "state": result.state, "ok": result.ok,
        "correlation_id": correlation_id,
    })
    return result.dict(exclude_none=True)


@app.post("/v3/actions/{action_id}/approve")
async def v3_approve_action_endpoint(request: Request, action_id: str):
    """V3 approve action."""
    return await _do_approve_action(request, action_id)


@app.post("/v1/actions/{action_id}/approve")
async def v1_approve_action_endpoint(request: Request, action_id: str):
    """V1 approve action (DEPRECATED)."""
    return _add_deprecation(await _do_approve_action(request, action_id))


async def _do_deny_action(request: Request, action_id: str):
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.deny(action_id)
    log_event({
        "level": "INFO", "service": "api-gateway", "operation": "action.deny",
        "action_id": action_id, "state": result.state, "ok": result.ok,
        "correlation_id": correlation_id,
    })
    return result.dict(exclude_none=True)


@app.post("/v3/actions/{action_id}/deny")
async def v3_deny_action_endpoint(request: Request, action_id: str):
    """V3 deny action."""
    return await _do_deny_action(request, action_id)


@app.post("/v1/actions/{action_id}/deny")
async def v1_deny_action_endpoint(request: Request, action_id: str):
    """V1 deny action (DEPRECATED)."""
    return _add_deprecation(await _do_deny_action(request, action_id))


async def _do_list_actions(state: Optional[str], session_id: Optional[str], limit: int, offset: int):
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    actions = await action_pipeline.store.list_actions(state=state, session_id=session_id, limit=limit, offset=offset)
    total = await action_pipeline.store.count(state=state)
    return {
        "ok": True,
        "actions": [a.dict(exclude_none=True) for a in actions],
        "total": total,
        "filters": {"state": state, "session_id": session_id, "limit": limit, "offset": offset},
    }


@app.get("/v3/actions")
async def v3_list_actions_endpoint(state: Optional[str] = None, session_id: Optional[str] = None, limit: int = 50, offset: int = 0):
    """V3 list actions."""
    return await _do_list_actions(state, session_id, limit, offset)


@app.get("/v1/actions")
async def v1_list_actions_endpoint(state: Optional[str] = None, session_id: Optional[str] = None, limit: int = 50, offset: int = 0):
    """V1 list actions (DEPRECATED)."""
    return _add_deprecation(await _do_list_actions(state, session_id, limit, offset))


# ============================================================================
# Capabilities (v3 canonical + v1 compat)
# ============================================================================

async def _do_capabilities():
    reg = get_capability_registry()
    caps = reg.list_all()
    return {
        "ok": True,
        "capabilities": [
            {
                "intent": c.intent, "display_name": c.display_name,
                "description": c.description, "risk_level": c.risk_level,
                "requires_confirmation": c.requires_confirmation,
                "implemented": c.implemented, "required_params": c.required_params,
                "optional_params": c.optional_params, "idempotent": c.idempotent,
                "reversible": c.reversible, "tags": list(c.tags),
            }
            for c in caps
        ],
        "stats": reg.stats(),
    }


@app.get("/v3/capabilities")
async def v3_capabilities_endpoint():
    """V3 list capabilities."""
    result = await _do_capabilities()
    result["contract_version"] = SONIA_CONTRACT
    return result


@app.get("/v1/capabilities")
async def v1_capabilities_endpoint():
    """V1 capabilities (DEPRECATED)."""
    return _add_deprecation(await _do_capabilities())


# ============================================================================
# Recovery & Observability (v3 canonical + v1 compat)
# ============================================================================

async def _do_health_summary():
    if not health_supervisor:
        return {"ok": False, "error": "Health supervisor not initialized"}
    return {"ok": True, **health_supervisor.summary()}


@app.get("/v3/health/summary")
async def v3_health_summary():
    return await _do_health_summary()


@app.get("/v1/health/summary")
async def v1_health_summary():
    return _add_deprecation(await _do_health_summary())


async def _do_breakers():
    reg = get_breaker_registry()
    return {"ok": True, "breakers": reg.summary()}


@app.get("/v3/breakers")
async def v3_breakers():
    return await _do_breakers()


@app.get("/v1/breakers")
async def v1_breakers():
    return _add_deprecation(await _do_breakers())


async def _do_reset_breaker(name: str):
    reg = get_breaker_registry()
    breaker = reg.get(name)
    if not breaker:
        return JSONResponse(status_code=404, content={
            "ok": False, "error": {"code": "NOT_FOUND", "message": f"Breaker '{name}' not found"},
        })
    await breaker.reset()
    log_event({"level": "INFO", "service": "api-gateway", "operation": "breaker.reset", "breaker": name})
    return {"ok": True, "breaker": breaker.to_dict()}


@app.post("/v3/breakers/{name}/reset")
async def v3_reset_breaker(name: str):
    return await _do_reset_breaker(name)


@app.post("/v1/breakers/{name}/reset")
async def v1_reset_breaker(name: str):
    result = await _do_reset_breaker(name)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


async def _do_breaker_metrics(last_n: int):
    reg = get_breaker_registry()
    return {"ok": True, "metrics": reg.metrics(last_n=last_n)}


@app.get("/v3/breakers/metrics")
async def v3_breaker_metrics(last_n: int = 50):
    return await _do_breaker_metrics(last_n)


@app.get("/v1/breakers/metrics")
async def v1_breaker_metrics(last_n: int = 50):
    return _add_deprecation(await _do_breaker_metrics(last_n))


# ============================================================================
# Dead Letter Queue (v3 canonical + v1 compat)
# ============================================================================

async def _do_list_dead_letters(limit: int, offset: int, include_replayed: bool):
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    dlq = get_dead_letter_queue()
    letters = await dlq.list_letters(limit=limit, offset=offset, include_replayed=include_replayed)
    total = await dlq.count(include_replayed=include_replayed)
    return {"ok": True, "dead_letters": [dl.to_dict() for dl in letters], "total": total}


@app.get("/v3/dead-letters")
async def v3_list_dead_letters(limit: int = 50, offset: int = 0, include_replayed: bool = False):
    return await _do_list_dead_letters(limit, offset, include_replayed)


@app.get("/v1/dead-letters")
async def v1_list_dead_letters(limit: int = 50, offset: int = 0, include_replayed: bool = False):
    return _add_deprecation(await _do_list_dead_letters(limit, offset, include_replayed))


async def _do_get_dead_letter(letter_id: str):
    dlq = get_dead_letter_queue()
    dl = await dlq.get(letter_id)
    if not dl:
        return JSONResponse(status_code=404, content={
            "ok": False, "error": {"code": "NOT_FOUND", "message": f"Dead letter {letter_id} not found"},
        })
    return {"ok": True, "dead_letter": dl.to_dict()}


@app.get("/v3/dead-letters/{letter_id}")
async def v3_get_dead_letter(letter_id: str):
    return await _do_get_dead_letter(letter_id)


@app.get("/v1/dead-letters/{letter_id}")
async def v1_get_dead_letter(letter_id: str):
    result = await _do_get_dead_letter(letter_id)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


async def _do_replay_dead_letter(request: Request, letter_id: str, dry_run: bool):
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    result = await action_pipeline.replay_dead_letter(letter_id, dry_run=dry_run)
    log_event({
        "level": "INFO", "service": "api-gateway", "operation": "dead_letter.replay",
        "letter_id": letter_id, "action_id": result.action_id, "state": result.state,
        "ok": result.ok, "dry_run": dry_run, "correlation_id": correlation_id,
    })
    return result.dict(exclude_none=True)


@app.post("/v3/dead-letters/{letter_id}/replay")
async def v3_replay_dead_letter(request: Request, letter_id: str, dry_run: bool = False):
    return await _do_replay_dead_letter(request, letter_id, dry_run)


@app.post("/v1/dead-letters/{letter_id}/replay")
async def v1_replay_dead_letter(request: Request, letter_id: str, dry_run: bool = False):
    return _add_deprecation(await _do_replay_dead_letter(request, letter_id, dry_run))


# ============================================================================
# Audit Trails (v3 canonical + v1 compat)
# ============================================================================

async def _do_list_audit_trails(limit: int, offset: int):
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    audit = get_audit_logger()
    trails = audit.list_trails(limit=limit, offset=offset)
    return {"ok": True, "trails": trails, "total": audit.count()}


@app.get("/v3/audit-trails")
async def v3_list_audit_trails(limit: int = 50, offset: int = 0):
    return await _do_list_audit_trails(limit, offset)


@app.get("/v1/audit-trails")
async def v1_list_audit_trails(limit: int = 50, offset: int = 0):
    return _add_deprecation(await _do_list_audit_trails(limit, offset))


async def _do_get_audit_trail(action_id: str):
    audit = get_audit_logger()
    trail = audit.get_trail(action_id)
    if not trail:
        return JSONResponse(status_code=404, content={
            "ok": False, "error": {"code": "NOT_FOUND", "message": f"Audit trail for {action_id} not found"},
        })
    return {"ok": True, "trail": trail.to_dict()}


@app.get("/v3/audit-trails/{action_id}")
async def v3_get_audit_trail(action_id: str):
    return await _do_get_audit_trail(action_id)


@app.get("/v1/audit-trails/{action_id}")
async def v1_get_audit_trail(action_id: str):
    result = await _do_get_audit_trail(action_id)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


# ============================================================================
# SLO Diagnostics (v4.7 Epic C — /v1/slo/status)
# ============================================================================

@app.get("/v1/slo/status")
async def v1_slo_status():
    """SLO diagnostics: current mode, breach history, recovery status."""
    from latency_budget import get_slo_guardrails
    guardrails = get_slo_guardrails()
    return guardrails.slo_status()


@app.get("/v3/slo/status")
async def v3_slo_status():
    """SLO diagnostics (v3 canonical)."""
    from latency_budget import get_slo_guardrails
    guardrails = get_slo_guardrails()
    return guardrails.slo_status()


# ============================================================================
# Diagnostic Snapshot (v3 canonical + v1 compat)
# ============================================================================

async def _do_diagnostics_snapshot(last_n: int):
    correlation_id = generate_correlation_id()
    snapshot = {"ok": True, "correlation_id": correlation_id, "timestamp": datetime.utcnow().isoformat() + "Z"}

    try:
        if health_supervisor:
            snapshot["health"] = health_supervisor.summary()
    except Exception as e:
        snapshot["health"] = {"error": str(e)}

    try:
        reg = get_breaker_registry()
        snapshot["breakers"] = reg.summary()
        snapshot["breaker_metrics"] = reg.metrics(last_n=last_n)
    except Exception as e:
        snapshot["breakers"] = {"error": str(e)}

    try:
        dlq = get_dead_letter_queue()
        count = await dlq.count(include_replayed=False)
        recent = await dlq.list_letters(limit=last_n, include_replayed=False)
        snapshot["dead_letters"] = {"unresolved": count, "recent": [dl.to_dict() for dl in recent]}
    except Exception as e:
        snapshot["dead_letters"] = {"error": str(e)}

    try:
        if action_pipeline:
            actions = await action_pipeline.store.list_actions(limit=last_n)
            snapshot["recent_actions"] = {"count": len(actions), "actions": [a.dict(exclude_none=True) for a in actions]}
    except Exception as e:
        snapshot["recent_actions"] = {"error": str(e)}

    return snapshot


@app.get("/v3/diagnostics/snapshot")
async def v3_diagnostics_snapshot(last_n: int = 50):
    return await _do_diagnostics_snapshot(last_n)


@app.get("/v1/diagnostics/snapshot")
async def v1_diagnostics_snapshot(last_n: int = 50):
    return _add_deprecation(await _do_diagnostics_snapshot(last_n))


# ============================================================================
# State Backup & Restore (v3 canonical + v1 compat)
# ============================================================================

async def _do_create_backup(label: str):
    mgr = get_backup_manager()
    dlq = get_dead_letter_queue()
    reg = get_breaker_registry()
    store = action_pipeline.store if action_pipeline else None
    manifest = await mgr.create_backup(dlq, store, reg, label=label)
    return {"ok": True, "backup": manifest}


@app.post("/v3/backups")
async def v3_create_backup(label: str = ""):
    return await _do_create_backup(label)


@app.post("/v1/backups")
async def v1_create_backup(label: str = ""):
    return _add_deprecation(await _do_create_backup(label))


async def _do_list_backups():
    mgr = get_backup_manager()
    backups = mgr.list_backups()
    return {"ok": True, "backups": backups, "total": len(backups)}


@app.get("/v3/backups")
async def v3_list_backups():
    return await _do_list_backups()


@app.get("/v1/backups")
async def v1_list_backups():
    return _add_deprecation(await _do_list_backups())


async def _do_verify_backup(backup_id: str):
    mgr = get_backup_manager()
    return await mgr.verify_backup(backup_id)


@app.get("/v3/backups/{backup_id}/verify")
async def v3_verify_backup(backup_id: str):
    return await _do_verify_backup(backup_id)


@app.get("/v1/backups/{backup_id}/verify")
async def v1_verify_backup(backup_id: str):
    result = await _do_verify_backup(backup_id)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


async def _do_restore_dlq(backup_id: str, dry_run: bool):
    mgr = get_backup_manager()
    dlq = get_dead_letter_queue()
    return await mgr.restore_dlq(backup_id, dlq, dry_run=dry_run)


@app.post("/v3/backups/{backup_id}/restore/dlq")
async def v3_restore_dlq(backup_id: str, dry_run: bool = True):
    return await _do_restore_dlq(backup_id, dry_run)


@app.post("/v1/backups/{backup_id}/restore/dlq")
async def v1_restore_dlq(backup_id: str, dry_run: bool = True):
    result = await _do_restore_dlq(backup_id, dry_run)
    if isinstance(result, dict):
        return _add_deprecation(result)
    return result


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
    import os as _os_main

    # v4.4 Epic A: TLS passthrough config
    _tls_cert = _os_main.environ.get("SONIA_TLS_CERT")
    _tls_key = _os_main.environ.get("SONIA_TLS_KEY")
    _ssl_kwargs = {}
    if _tls_cert and _tls_key:
        _ssl_kwargs["ssl_certfile"] = _tls_cert
        _ssl_kwargs["ssl_keyfile"] = _tls_key

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=7000,
        reload=False,
        **_ssl_kwargs,
    )
