"""
Pipecat Main Service
FastAPI application with session management and WebSocket support.
"""

import json
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Optional

# Canonical version
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION

from sessions import SessionManager, SessionState
from routes.ws import websocket_handler
from clients.api_gateway_client import ApiGatewayClient, ApiGatewayClientError

# Voice loop hardening modules
from app.session_manager import VoiceSessionManager
from app.telemetry import TurnTelemetryLogger
from app.model_router_client import close_client as close_model_router_client

# v2.7: Voice turn router (gateway stream pipeline)
from app.voice_turn_router import VoiceTurnRouter, VoiceTurnRecord

# ============================================================================
# FastAPI Application Setup
# ============================================================================

# Global managers and clients
session_manager: Optional[SessionManager] = None
api_gateway_client: Optional[ApiGatewayClient] = None
voice_session_manager: Optional[VoiceSessionManager] = None
turn_telemetry: Optional[TurnTelemetryLogger] = None
voice_turn_router: Optional[VoiceTurnRouter] = None  # v2.7


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return f"req_{uuid.uuid4().hex[:12]}"


def log_event(event_dict: dict):
    """Log event as JSON line."""
    event_dict.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
    print(json.dumps(event_dict))


@asynccontextmanager
async def _lifespan(a):
    """Startup and shutdown lifecycle for Pipecat."""
    global session_manager, api_gateway_client, voice_session_manager, turn_telemetry, voice_turn_router

    session_manager = SessionManager(persist_dir="S:\\data\\sessions")
    session_manager.load_persisted()

    api_gateway_client = ApiGatewayClient(base_url="http://127.0.0.1:7000")

    voice_session_manager = VoiceSessionManager(cleanup_timeout=5.0)
    turn_telemetry = TurnTelemetryLogger()

    voice_turn_router = VoiceTurnRouter(
        gateway_url="http://127.0.0.1:7000",
        turn_timeout=30.0,
    )

    log_event({
        "level": "INFO",
        "service": "pipecat",
        "event": "startup",
        "message": f"Pipecat {SONIA_VERSION} initialized with voice turn router + gateway stream pipeline"
    })

    yield  # ── app is running ──

    if voice_turn_router:
        closed = await voice_turn_router.close_all()
        log_event({
            "level": "INFO",
            "service": "pipecat",
            "event": "voice_turn_router_closed",
            "sessions_closed": closed,
        })

    if voice_session_manager:
        closed = await voice_session_manager.close_all(reason="shutdown")
        log_event({
            "level": "INFO",
            "service": "pipecat",
            "event": "voice_sessions_closed",
            "count": closed,
        })

    await close_model_router_client()

    if api_gateway_client:
        await api_gateway_client.close()

    log_event({
        "level": "INFO",
        "service": "pipecat",
        "event": "shutdown",
        "message": "Pipecat shutdown complete"
    })


app = FastAPI(
    title="Pipecat",
    description="Session management and WebSocket real-time communication",
    version=SONIA_VERSION,
    lifespan=_lifespan,
)


# ============================================================================
# Universal Endpoints (Contract Required)
# ============================================================================

@app.get("/healthz")
async def healthz():
    """Health check endpoint — enriched with voice loop runtime details."""
    health = {
        "ok": True,
        "service": "pipecat",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Voice loop details (non-breaking: only present when components are init'd)
    if voice_session_manager is not None:
        health["voice"] = {
            "active_sessions": voice_session_manager.active_count,
        }

    if turn_telemetry is not None:
        health["telemetry"] = {
            "turns_logged": turn_telemetry.turn_count,
            "log_path": str(turn_telemetry.log_path),
        }

    # v2.7: Voice turn router stats
    if voice_turn_router is not None:
        health["voice_turn_router"] = voice_turn_router.get_stats()

    return health


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "pipecat",
        "status": "online",
        "version": SONIA_VERSION
    }


@app.get("/status")
async def status():
    """Status endpoint with detailed information."""
    active_sessions = len(session_manager.list(state=SessionState.ACTIVE))
    all_sessions = len(session_manager.list())
    
    return {
        "service": "pipecat",
        "status": "online",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": SONIA_VERSION,
        "sessions": {
            "active": active_sessions,
            "total": all_sessions
        }
    }


# ============================================================================
# Session Endpoints
# ============================================================================

@app.post("/session/start")
async def session_start(
    request: Request,
    user_id: Optional[str] = None,
    metadata: Optional[dict] = None
):
    """
    Start new session.
    
    Request:
    ```json
    {
        "user_id": "optional_user_id",
        "metadata": {"custom_key": "custom_value"}
    }
    ```
    
    Response: Standard envelope with session_id.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    try:
        session = session_manager.create(user_id=user_id, metadata=metadata)
        
        log_event({
            "level": "INFO",
            "service": "pipecat",
            "operation": "session_start",
            "session_id": session.id,
            "correlation_id": correlation_id
        })
        
        return {
            "ok": True,
            "service": "pipecat",
            "operation": "session_start",
            "correlation_id": correlation_id,
            "duration_ms": 0,
            "data": {
                "session_id": session.id,
                "state": session.state.value,
                "created_at": session.created_at.isoformat() + "Z"
            },
            "error": None
        }
    
    except Exception as e:
        log_event({
            "level": "ERROR",
            "service": "pipecat",
            "operation": "session_start",
            "error": str(e),
            "correlation_id": correlation_id
        })
        
        return {
            "ok": False,
            "service": "pipecat",
            "operation": "session_start",
            "correlation_id": correlation_id,
            "duration_ms": 0,
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(e),
                "details": {}
            }
        }


@app.get("/session/{session_id}")
async def session_get(session_id: str, request: Request):
    """
    Get session info and message history.
    
    Response: Session details with messages.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    session = session_manager.get(session_id)
    if not session:
        return {
            "ok": False,
            "service": "pipecat",
            "operation": "session_get",
            "correlation_id": correlation_id,
            "duration_ms": 0,
            "data": None,
            "error": {
                "code": "NOT_FOUND",
                "message": f"Session {session_id} not found",
                "details": {}
            }
        }
    
    return {
        "ok": True,
        "service": "pipecat",
        "operation": "session_get",
        "correlation_id": correlation_id,
        "duration_ms": 0,
        "data": {
            **session.to_dict(),
            "messages": session.get_messages()
        },
        "error": None
    }


@app.post("/session/stop")
async def session_stop(session_id: str, request: Request, reason: Optional[str] = None):
    """
    Stop session.
    
    Request:
    ```json
    {
        "session_id": "session_uuid",
        "reason": "user_requested"
    }
    ```
    
    Response: Standard envelope with closed session.
    """
    correlation_id = request.headers.get("X-Correlation-ID", generate_correlation_id())
    
    session = session_manager.close(session_id)
    if not session:
        return {
            "ok": False,
            "service": "pipecat",
            "operation": "session_stop",
            "correlation_id": correlation_id,
            "duration_ms": 0,
            "data": None,
            "error": {
                "code": "NOT_FOUND",
                "message": f"Session {session_id} not found",
                "details": {}
            }
        }
    
    log_event({
        "level": "INFO",
        "service": "pipecat",
        "operation": "session_stop",
        "session_id": session_id,
        "reason": reason or "user_requested",
        "correlation_id": correlation_id
    })
    
    return {
        "ok": True,
        "service": "pipecat",
        "operation": "session_stop",
        "correlation_id": correlation_id,
        "duration_ms": 0,
        "data": session.to_dict(),
        "error": None
    }


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket connection for real-time session communication.
    
    Connection URL: ws://127.0.0.1:7030/ws/{session_id}
    
    Sends MESSAGE, SESSION_START, STATUS, ERROR events.
    Receives MESSAGE, SESSION_STOP, STATUS events.
    """
    correlation_id = generate_correlation_id()
    
    # Define chat handler that calls API Gateway
    async def chat_handler(message: str, session_id: str, correlation_id: str) -> str:
        """Handler that forwards messages to API Gateway."""
        try:
            response = await api_gateway_client.chat(
                message=message,
                session_id=session_id,
                correlation_id=correlation_id
            )
            return response
        except ApiGatewayClientError as e:
            return f"Error: {e.code} - {e.message}"
    
    await websocket_handler(
        websocket=websocket,
        session_id=session_id,
        session_manager=session_manager,
        chat_handler=chat_handler,
        correlation_id=correlation_id
    )


@app.websocket("/v1/voice/{session_id}")
async def voice_stream_endpoint(websocket: WebSocket, session_id: str):
    """
    v2.7 Voice Stream — routes through gateway's full turn pipeline.

    Connection URL: ws://127.0.0.1:7030/v1/voice/{session_id}

    Protocol (JSON):
      Client -> Server:
        {"type": "input.text", "text": "Hello"}
        {"type": "control.end"}

      Server -> Client:
        {"type": "session.ready", "gateway_session_id": "..."}
        {"type": "response.partial", "text": "..."}
        {"type": "response.final", "text": "...", "turn_id": "...", "latency_ms": ...}
        {"type": "error", "message": "..."}
        {"type": "tool.call", "tool_name": "...", "status": "..."}

    The session_id is Pipecat's local session ID. A gateway session
    is created lazily on first turn and persists for the WS lifetime.
    """
    await websocket.accept()
    correlation_id = generate_correlation_id()

    log_event({
        "level": "INFO",
        "service": "pipecat",
        "event": "voice_stream_connected",
        "session_id": session_id,
        "correlation_id": correlation_id,
    })

    try:
        # Notify client the stream is ready
        await websocket.send_json({
            "type": "session.ready",
            "session_id": session_id,
            "correlation_id": correlation_id,
        })

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            msg_type = msg.get("type", "")

            if msg_type == "control.end":
                break

            if msg_type == "input.text":
                text = msg.get("text", "").strip()
                if not text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Empty input text",
                    })
                    continue

                turn_corr = msg.get("correlation_id", generate_correlation_id())

                # Route through the full gateway stream pipeline
                record = await voice_turn_router.process_turn(
                    user_text=text,
                    pipecat_session_id=session_id,
                    correlation_id=turn_corr,
                )

                if record.ok:
                    await websocket.send_json({
                        "type": "response.final",
                        "text": record.assistant_text,
                        "turn_id": record.turn_id,
                        "latency_ms": round(record.latency_ms, 1),
                        "tool_calls": len(record.tool_calls),
                        "partial_count": record.partial_count,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": record.error,
                        "turn_id": record.turn_id,
                        "latency_ms": round(record.latency_ms, 1),
                    })

                # Log telemetry
                if turn_telemetry:
                    turn_telemetry.log_turn({
                        "turn_id": record.turn_id,
                        "session_id": session_id,
                        "correlation_id": turn_corr,
                        "user_text_len": len(text),
                        "assistant_text_len": len(record.assistant_text),
                        "tool_calls": len(record.tool_calls),
                        "latency_ms": round(record.latency_ms, 1),
                        "gateway_latency_ms": round(record.gateway_latency_ms, 1),
                        "ok": record.ok,
                        "error": record.error[:200] if record.error else "",
                        "route": "v1/voice",
                    })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        log_event({
            "level": "INFO",
            "service": "pipecat",
            "event": "voice_stream_disconnected",
            "session_id": session_id,
        })
    except Exception as e:
        log_event({
            "level": "ERROR",
            "service": "pipecat",
            "event": "voice_stream_error",
            "session_id": session_id,
            "error": str(e),
        })
    finally:
        # Cleanup the gateway stream client for this session
        if voice_turn_router:
            await voice_turn_router.close_session(session_id)


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
            "service": "pipecat",
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
        "service": "pipecat",
        "error": str(exc),
        "error_type": type(exc).__name__,
        "path": request.url.path,
        "correlation_id": correlation_id
    })
    
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "service": "pipecat",
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
        port=7030,
        reload=False
    )
