"""
API Gateway — UI Stream Route (v3.0)

WS /v1/ui/stream

Bidirectional WebSocket for the Electron UI client. Implements the
control ACK protocol that connection.ts (v2.6-c1) expects, plus the
text conversation bridge (v3.0) that routes input.text through the
full turn pipeline (memory recall -> model chat -> tool exec -> memory write).

Inbound (UI -> gateway):
  { type: "input.text", text: str }           ** v3.0: conversation bridge **
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

from routes.turn import handle_turn
from schemas.turn import TurnRequest

logger = logging.getLogger("api-gateway.routes.ui_stream")


# ---------------------------------------------------------------------------
# Client holder — injected by main.py at startup so the WS handler
# can call handle_turn() without circular imports.
# ---------------------------------------------------------------------------

class _ClientHolder:
    """Holds references to the downstream clients for the turn pipeline."""
    __slots__ = ("memory_client", "router_client", "openclaw_client")

    def __init__(self):
        self.memory_client = None
        self.router_client = None
        self.openclaw_client = None

    @property
    def ready(self) -> bool:
        return all([self.memory_client, self.router_client, self.openclaw_client])


_clients = _ClientHolder()


def inject_clients(memory_client, router_client, openclaw_client):
    """Called from main.py lifespan to wire up downstream clients."""
    _clients.memory_client = memory_client
    _clients.router_client = router_client
    _clients.openclaw_client = openclaw_client


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
        # v3.0: real latency tracking
        self._last_latency: Dict[str, Any] = {}
        self._last_turn_id: Optional[str] = None

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
        """Build diagnostics snapshot for the UI — wired to real data (v3.0)."""
        lat = self._last_latency or {}
        return {
            "session_id": self.session_id,
            "uptime_seconds": round(time.time() - self.created_at, 1),
            "turn_count": self.turn_count,
            "latency": {
                "asr_ms": lat.get("asr_ms", 0),
                "model_ms": lat.get("model_ms", 0),
                "tool_ms": lat.get("tool_ms", 0),
                "memory_ms": lat.get("memory_read_ms", 0) + lat.get("memory_write_ms", 0),
                "total_ms": lat.get("total_ms", 0),
                "last_updated": round(self.last_activity, 1),
            },
            "breaker_states": {},
            "dlq_depth": 0,
            "privacy_status": "enabled" if self.controls["privacyEnabled"] else "disabled",
            "vision_buffer_frames": 0,
            "last_error": None,
            "last_turn_id": self._last_turn_id,
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

    elif msg_type == "input.text":
        text = (msg.get("text") or "").strip()
        if not text:
            await ws.send_json({"type": "error", "message": "empty_input_text"})
            return

        # Guard against concurrent turns
        if state.conversation_state != "idle":
            await ws.send_json({"type": "error", "message": "turn_in_progress"})
            return

        # Fire-and-forget in background so WS recv loop stays alive
        asyncio.create_task(
            _handle_text_turn(ws, state, text)
        )

    else:
        await ws.send_json({
            "type": "error",
            "message": f"unknown_message_type:{msg_type}",
        })


async def _handle_text_turn(ws: Any, state: UISessionState, text: str) -> None:
    """
    v3.0: Bridge a user text message through the full turn pipeline.

    Flow:
      1. Echo turn.user back to UI
      2. Transition conversation state: idle -> thinking
      3. Call handle_turn() (memory recall -> model chat -> tools -> memory write)
      4. Send turn.assistant with response
      5. Update latency diagnostics
      6. Transition back to idle
    """
    correlation_id = f"req_{uuid.uuid4().hex[:12]}"
    try:
        # 1. Echo user message
        await ws.send_json({"type": "turn.user", "text": text})

        # 2. Transition to thinking
        state.conversation_state = "thinking"
        await ws.send_json({"type": "state.conversation", "state": "thinking"})

        # 3. Check clients are wired up
        if not _clients.ready:
            await ws.send_json({"type": "error", "message": "backend_not_ready"})
            state.conversation_state = "idle"
            await ws.send_json({"type": "state.conversation", "state": "idle"})
            return

        # 4. Build TurnRequest and call the pipeline
        turn_req = TurnRequest(
            user_id="ui-user",
            conversation_id=state.session_id,
            input_text=text,
            profile="chat_low_latency",
        )

        turn_resp = await handle_turn(
            request=turn_req,
            memory_client=_clients.memory_client,
            router_client=_clients.router_client,
            openclaw_client=_clients.openclaw_client,
            correlation_id=correlation_id,
        )

        # 5. Send assistant response
        assistant_text = turn_resp.assistant_text or ""
        if turn_resp.ok and assistant_text:
            state.conversation_state = "speaking"
            await ws.send_json({"type": "state.conversation", "state": "speaking"})
            await ws.send_json({"type": "turn.assistant", "text": assistant_text})
        elif not turn_resp.ok:
            err = turn_resp.error or {}
            await ws.send_json({
                "type": "error",
                "message": err.get("message", "turn_failed"),
            })
            # Still send whatever text we got (may be partial)
            if assistant_text:
                await ws.send_json({"type": "turn.assistant", "text": assistant_text})

        # 6. Update diagnostics with real latency
        extra = getattr(turn_resp, "_extra_fields", None)
        latency_data = extra.get("latency", {}) if extra else {}
        state._last_latency = latency_data
        state._last_turn_id = turn_resp.turn_id
        state.turn_count += 1
        state.last_activity = time.time()

    except Exception as exc:
        logger.error("text turn failed: %s", exc, exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": f"turn_error:{exc}"})
        except Exception:
            pass
    finally:
        state.conversation_state = "idle"
        try:
            await ws.send_json({"type": "state.conversation", "state": "idle"})
        except Exception:
            pass


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
