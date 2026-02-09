"""
API Gateway — UI Stream Route (v2.7-m3)

WS /v1/ui/stream

Bidirectional WebSocket for the Electron UI client. Implements the
control ACK protocol that connection.ts (v2.6-c1) expects:

Inbound (UI -> gateway):
  { type: "control.toggle", field: str, value: bool }
  { type: "control.interrupt" }
  { type: "control.replay" }
  { type: "control.hold", active: bool }

Outbound (gateway -> UI):
  { type: "session.created", session_id: str }
  { type: "state.conversation", state: str }
  { type: "state.emotion", emotion: str }
  { type: "state.amplitude", value: float }
  { type: "ack.control", field: str }
  { type: "nack.control", field: str, reason: str }
  { type: "ack.interrupt" }
  { type: "ack.replay" }
  { type: "turn.assistant", text: str }
  { type: "turn.user", text: str }
  { type: "diagnostics", data: {...} }
  { type: "error", message: str }

The UI stream maintains per-connection state and bridges
control requests to the session/turn pipeline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("api-gateway.routes.ui_stream")


# ---------------------------------------------------------------------------
# UI session state
# ---------------------------------------------------------------------------

class UISessionState:
    """Per-connection UI state tracking."""

    # Valid control fields that the UI can toggle
    TOGGLEABLE_FIELDS: Set[str] = {"micEnabled", "camEnabled", "privacyEnabled", "holdActive"}

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.controls: Dict[str, bool] = {
            "micEnabled": True,
            "camEnabled": False,
            "privacyEnabled": False,
            "holdActive": False,
        }
        self.conversation_state = "idle"
        self.emotion = "neutral"
        self.amplitude = 0.0
        self.turn_count = 0
        self.last_activity = time.time()
        self.diagnostics_interval_s = 5.0

    def toggle_control(self, field: str, value: bool) -> tuple[bool, str]:
        """
        Apply a control toggle. Returns (success, reason).
        On success, the control is updated. On failure, reason explains why.
        """
        if field not in self.TOGGLEABLE_FIELDS:
            return False, f"unknown_field:{field}"

        self.controls[field] = value
        self.last_activity = time.time()
        return True, ""

    def to_diagnostics(self) -> Dict[str, Any]:
        """Build diagnostics snapshot for the UI."""
        return {
            "session_id": self.session_id,
            "uptime_seconds": round(time.time() - self.created_at, 1),
            "turn_count": self.turn_count,
            "latency": {
                "asr_ms": 0,
                "model_ms": 0,
                "tool_ms": 0,
                "memory_ms": 0,
                "total_ms": 0,
                "last_updated": 0,
            },
            "breaker_states": {},
            "dlq_depth": 0,
            "privacy_status": "enabled" if self.controls["privacyEnabled"] else "disabled",
            "vision_buffer_frames": 0,
            "last_error": None,
        }


# ---------------------------------------------------------------------------
# UI stream connection manager
# ---------------------------------------------------------------------------

class UIStreamManager:
    """
    Manages active UI WebSocket connections. Provides:
    - Per-connection state tracking
    - Broadcast to all connected UIs
    - Control ACK/NACK dispatch
    """

    MAX_CONNECTIONS = 10

    def __init__(self):
        self._connections: Dict[str, _UIConnection] = {}  # conn_id -> connection
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def register(self, conn_id: str, ws: Any, session_id: str) -> UISessionState:
        """Register a new UI connection."""
        async with self._lock:
            if len(self._connections) >= self.MAX_CONNECTIONS:
                raise RuntimeError("MAX_UI_CONNECTIONS")
            state = UISessionState(session_id)
            self._connections[conn_id] = _UIConnection(
                conn_id=conn_id,
                ws=ws,
                state=state,
            )
            return state

    async def unregister(self, conn_id: str) -> None:
        """Remove a UI connection."""
        async with self._lock:
            self._connections.pop(conn_id, None)

    async def broadcast(self, message: Dict[str, Any]) -> int:
        """Send message to all connected UIs. Returns delivery count."""
        async with self._lock:
            conns = list(self._connections.values())

        delivered = 0
        for conn in conns:
            try:
                await conn.ws.send_json(message)
                delivered += 1
            except Exception:
                pass
        return delivered

    def get_state(self, conn_id: str) -> Optional[UISessionState]:
        """Get state for a connection."""
        conn = self._connections.get(conn_id)
        return conn.state if conn else None


class _UIConnection:
    __slots__ = ("conn_id", "ws", "state")

    def __init__(self, conn_id: str, ws: Any, state: UISessionState):
        self.conn_id = conn_id
        self.ws = ws
        self.state = state


# ---------------------------------------------------------------------------
# Singleton manager
# ---------------------------------------------------------------------------

ui_stream_manager = UIStreamManager()


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------

async def handle_ui_stream(
    websocket: Any,
    session_id: str,
    correlation_id: str = "",
) -> None:
    """
    Handle a UI WebSocket connection. Called from the FastAPI route.

    1. Accept + register connection
    2. Send session.created ack
    3. Start diagnostics push loop
    4. Receive + dispatch control messages
    5. Cleanup on disconnect
    """
    conn_id = f"ui_{uuid.uuid4().hex[:8]}"
    if not correlation_id:
        correlation_id = f"req_{uuid.uuid4().hex[:12]}"

    try:
        state = await ui_stream_manager.register(conn_id, websocket, session_id)
    except RuntimeError:
        await websocket.send_json({"type": "error", "message": "MAX_UI_CONNECTIONS"})
        await websocket.close(1013, "MAX_UI_CONNECTIONS")
        return

    logger.info("UI stream connected: conn=%s session=%s", conn_id, session_id)

    # Send session.created
    await websocket.send_json({
        "type": "session.created",
        "session_id": session_id,
    })

    # Start diagnostics push task
    diag_task = asyncio.create_task(_diagnostics_loop(websocket, state))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                await websocket.send_json({"type": "error", "message": "invalid_json"})
                continue

            msg_type = msg.get("type", "")
            await _dispatch_ui_message(websocket, state, msg_type, msg)

    except Exception:
        pass  # WebSocket disconnect
    finally:
        diag_task.cancel()
        try:
            await diag_task
        except asyncio.CancelledError:
            pass
        await ui_stream_manager.unregister(conn_id)
        logger.info("UI stream disconnected: conn=%s", conn_id)


async def _dispatch_ui_message(
    ws: Any,
    state: UISessionState,
    msg_type: str,
    msg: Dict[str, Any],
) -> None:
    """Route an inbound UI message to the appropriate handler."""

    if msg_type == "control.toggle":
        field = msg.get("field", "")
        value = msg.get("value")
        if value is None or not field:
            await ws.send_json({
                "type": "nack.control",
                "field": field,
                "reason": "missing_field_or_value",
            })
            return

        ok, reason = state.toggle_control(field, bool(value))
        if ok:
            await ws.send_json({"type": "ack.control", "field": field})
            logger.debug("ACK control.toggle %s=%s", field, value)
        else:
            await ws.send_json({
                "type": "nack.control",
                "field": field,
                "reason": reason,
            })

    elif msg_type == "control.interrupt":
        # ACK immediately; in real integration, this cancels the active turn
        state.conversation_state = "idle"
        await ws.send_json({"type": "ack.interrupt"})

    elif msg_type == "control.replay":
        # ACK immediately; in real integration, this replays the last turn
        await ws.send_json({"type": "ack.replay"})

    elif msg_type == "control.hold":
        active = msg.get("active", False)
        state.controls["holdActive"] = bool(active)
        await ws.send_json({"type": "ack.control", "field": "holdActive"})

    else:
        await ws.send_json({
            "type": "error",
            "message": f"unknown_message_type:{msg_type}",
        })


async def _diagnostics_loop(ws: Any, state: UISessionState) -> None:
    """Background task that pushes diagnostics to the UI at intervals."""
    try:
        while True:
            await asyncio.sleep(state.diagnostics_interval_s)
            diag = state.to_diagnostics()
            try:
                await ws.send_json({"type": "diagnostics", "data": diag})
            except Exception:
                break
    except asyncio.CancelledError:
        pass
