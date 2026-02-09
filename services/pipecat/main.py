"""
Pipecat Main Service
FastAPI application with session management and WebSocket support.
"""

import json
import sys
import uuid
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from datetime import datetime
from typing import Optional

from sessions import SessionManager, SessionState
from routes.ws import websocket_handler
from clients.api_gateway_client import ApiGatewayClient, ApiGatewayClientError

# ============================================================================
# FastAPI Application Setup
# ============================================================================

app = FastAPI(
    title="Pipecat",
    description="Session management and WebSocket real-time communication",
    version="1.0.0"
)

# Global managers and clients
session_manager: Optional[SessionManager] = None
api_gateway_client: Optional[ApiGatewayClient] = None


def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return f"req_{uuid.uuid4().hex[:12]}"


def log_event(event_dict: dict):
    """Log event as JSON line."""
    event_dict.setdefault("timestamp", datetime.utcnow().isoformat() + "Z")
    print(json.dumps(event_dict))


@app.on_event("startup")
async def startup_event():
    """Initialize session manager and clients."""
    global session_manager, api_gateway_client
    
    # Create session manager with optional persistence
    session_manager = SessionManager(persist_dir="S:\\data\\sessions")
    session_manager.load_persisted()
    
    # Initialize API Gateway client
    api_gateway_client = ApiGatewayClient(base_url="http://127.0.0.1:7000")
    
    log_event({
        "level": "INFO",
        "service": "pipecat",
        "event": "startup",
        "message": "Pipecat initialized with session manager"
    })


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources."""
    global api_gateway_client
    
    if api_gateway_client:
        await api_gateway_client.close()
    
    log_event({
        "level": "INFO",
        "service": "pipecat",
        "event": "shutdown",
        "message": "Pipecat shutdown complete"
    })


# ============================================================================
# Universal Endpoints (Contract Required)
# ============================================================================

@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    return {
        "ok": True,
        "service": "pipecat",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "pipecat",
        "status": "online",
        "version": "1.0.0"
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
        "version": "1.0.0",
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
