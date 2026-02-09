"""
Gateway Stream Client -- v2.7-m1

WebSocket client that connects Pipecat to the API Gateway's
/v1/stream/{session_id} for real turn pipeline round-trips.

Protocol (JSON over WS):
  Send:  {"type": "input.text", "text": "...", "correlation_id": "req_XXX"}
  Recv:  {"type": "response.final", "payload": {"text": "..."}}
         {"type": "response.partial", "payload": {"text": "..."}}
         {"type": "error", "payload": {"message": "..."}}
         {"type": "ack", "payload": {"session_id": "..."}}
         {"type": "tool.call.requested", ...}
         {"type": "tool.call.result", ...}
         {"type": "safety.confirmation.required", ...}

Lifecycle:
  1. Create gateway session via POST /v1/sessions
  2. Open WS to /v1/stream/{session_id}
  3. Exchange turns (input.text -> response.final)
  4. Close WS + delete session on shutdown
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx

logger = logging.getLogger("pipecat.clients.gateway_stream")


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class StreamState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class TurnResult:
    """Result of a single turn through the gateway stream."""

    __slots__ = (
        "ok", "turn_id", "assistant_text", "tool_calls",
        "partial_texts", "latency_ms", "error",
        "correlation_id", "events",
    )

    def __init__(self):
        self.ok: bool = False
        self.turn_id: str = ""
        self.assistant_text: str = ""
        self.tool_calls: List[Dict[str, Any]] = []
        self.partial_texts: List[str] = []
        self.latency_ms: float = 0.0
        self.error: str = ""
        self.correlation_id: str = ""
        self.events: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GatewayStreamClient:
    """
    Connects to gateway /v1/stream/{session_id} for real turn pipeline.

    Usage:
        client = GatewayStreamClient("http://127.0.0.1:7000")
        session_id = await client.create_session(user_id="u1")
        await client.connect(session_id)
        result = await client.send_turn("Hello, Sonia")
        await client.disconnect()
    """

    TURN_TIMEOUT_S = 30.0
    RECONNECT_BASE_S = 1.0
    RECONNECT_CAP_S = 16.0
    MAX_RECONNECT = 10

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:7000",
        on_partial: Optional[Callable[[str], Coroutine]] = None,
        on_event: Optional[Callable[[Dict[str, Any]], Coroutine]] = None,
    ):
        self.gateway_url = gateway_url.rstrip("/")
        self.on_partial = on_partial
        self.on_event = on_event

        self._state = StreamState.DISCONNECTED
        self._session_id: Optional[str] = None
        self._ws: Optional[Any] = None  # websockets connection
        self._http = httpx.AsyncClient(timeout=10.0)
        self._recv_task: Optional[asyncio.Task] = None
        self._turn_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._reconnect_attempts = 0
        self._intentional_close = False

    @property
    def state(self) -> StreamState:
        return self._state

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    # -- Session lifecycle --

    async def create_session(
        self,
        user_id: str = "pipecat-voice",
        conversation_id: str = "",
        profile: str = "default",
        correlation_id: str = "",
    ) -> str:
        """Create a gateway session via REST. Returns session_id."""
        if not correlation_id:
            correlation_id = f"req_{uuid.uuid4().hex[:12]}"

        resp = await self._http.post(
            f"{self.gateway_url}/v1/sessions",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id or f"voice-{uuid.uuid4().hex[:8]}",
                "profile": profile,
                "metadata": {"source": "pipecat", "type": "voice"},
            },
            headers={"X-Correlation-ID": correlation_id},
        )
        data = resp.json()
        if not data.get("ok"):
            err = data.get("error", {}).get("message", "unknown")
            raise RuntimeError(f"Failed to create session: {err}")

        self._session_id = data["session_id"]
        logger.info("Created gateway session %s", self._session_id)
        return self._session_id

    async def delete_session(self) -> bool:
        """Delete the gateway session via REST."""
        if not self._session_id:
            return False
        try:
            resp = await self._http.delete(
                f"{self.gateway_url}/v1/sessions/{self._session_id}",
            )
            data = resp.json()
            logger.info("Deleted session %s: %s", self._session_id, data.get("ok"))
            return data.get("ok", False)
        except Exception as e:
            logger.warning("Failed to delete session %s: %s", self._session_id, e)
            return False

    # -- WS connection --

    async def connect(self, session_id: Optional[str] = None) -> None:
        """Open WS to gateway stream. Creates session if needed."""
        if session_id:
            self._session_id = session_id
        if not self._session_id:
            await self.create_session()

        self._intentional_close = False
        await self._do_connect()

    async def disconnect(self) -> None:
        """Gracefully close WS + cleanup."""
        self._intentional_close = True
        self._state = StreamState.DISCONNECTED
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def close(self) -> None:
        """Full shutdown: disconnect WS + delete session + close HTTP."""
        await self.disconnect()
        await self.delete_session()
        await self._http.aclose()

    # -- Turn exchange --

    async def send_turn(
        self,
        text: str,
        correlation_id: str = "",
        timeout: float = 0,
    ) -> TurnResult:
        """
        Send a text turn and wait for the final response.

        Returns TurnResult with assistant_text, tool_calls, latency, etc.
        Collects partial responses if on_partial callback is set.
        """
        if self._state != StreamState.CONNECTED:
            result = TurnResult()
            result.error = f"Not connected (state={self._state.value})"
            return result

        if not correlation_id:
            correlation_id = f"req_{uuid.uuid4().hex[:12]}"
        if timeout <= 0:
            timeout = self.TURN_TIMEOUT_S

        turn_id = f"turn_{uuid.uuid4().hex[:8]}"
        result = TurnResult()
        result.turn_id = turn_id
        result.correlation_id = correlation_id

        # Drain any stale messages
        while not self._turn_queue.empty():
            try:
                self._turn_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Send input
        msg = {
            "type": "input.text",
            "text": text,
            "turn_id": turn_id,
            "correlation_id": correlation_id,
        }
        t0 = time.monotonic()
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            result.error = f"Send failed: {e}"
            return result

        # Collect response events until response.final or timeout
        deadline = t0 + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result.error = "Turn timeout"
                break
            try:
                event = await asyncio.wait_for(
                    self._turn_queue.get(), timeout=remaining
                )
            except asyncio.TimeoutError:
                result.error = "Turn timeout"
                break

            result.events.append(event)
            etype = event.get("type", "")

            if etype == "response.partial":
                partial = event.get("payload", {}).get("text", "")
                result.partial_texts.append(partial)
                if self.on_partial:
                    await self.on_partial(partial)

            elif etype == "response.final":
                payload = event.get("payload", {})
                result.assistant_text = payload.get("text", "")
                result.ok = True
                break

            elif etype == "tool.call.requested":
                result.tool_calls.append(event.get("payload", {}))

            elif etype == "tool.call.result":
                result.tool_calls.append(event.get("payload", {}))

            elif etype == "error":
                result.error = event.get("payload", {}).get("message", "unknown")
                break

        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    # -- Internal WS management --

    async def _do_connect(self) -> None:
        """Establish WebSocket connection to gateway stream."""
        try:
            import websockets
        except ImportError:
            raise RuntimeError("websockets package required: pip install websockets")

        ws_url = self.gateway_url.replace("http://", "ws://").replace("https://", "wss://")
        ws_url = f"{ws_url}/v1/stream/{self._session_id}"

        is_reconnect = self._reconnect_attempts > 0
        self._state = StreamState.RECONNECTING if is_reconnect else StreamState.CONNECTING
        logger.info("Connecting to %s (attempt %d)", ws_url, self._reconnect_attempts + 1)

        try:
            self._ws = await websockets.connect(
                ws_url,
                open_timeout=10,
                close_timeout=5,
            )
        except Exception as e:
            logger.error("WS connect failed: %s", e)
            self._state = StreamState.ERROR
            await self._schedule_reconnect()
            return

        self._state = StreamState.CONNECTED
        self._reconnect_attempts = 0
        logger.info("Connected to gateway stream (session=%s)", self._session_id)

        # Start background receiver
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self) -> None:
        """Background task: receive WS messages and dispatch."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                etype = msg.get("type", "")

                # Dispatch to event callback
                if self.on_event:
                    try:
                        await self.on_event(msg)
                    except Exception:
                        pass

                # Route turn-related events to the turn queue
                if etype in (
                    "response.partial", "response.final",
                    "tool.call.requested", "tool.call.result",
                    "safety.confirmation.required",
                    "error",
                ):
                    await self._turn_queue.put(msg)
                elif etype == "ack":
                    logger.debug("Stream ack: %s", msg.get("payload", {}))

        except asyncio.CancelledError:
            return
        except Exception as e:
            if self._intentional_close:
                return
            logger.warning("WS recv error: %s", e)
            self._state = StreamState.RECONNECTING
            await self._schedule_reconnect()

    async def _schedule_reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if self._intentional_close:
            return
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self.MAX_RECONNECT:
            self._state = StreamState.ERROR
            logger.error("Max reconnect attempts (%d) exceeded", self.MAX_RECONNECT)
            return

        delay = min(
            self.RECONNECT_BASE_S * (2 ** (self._reconnect_attempts - 1)),
            self.RECONNECT_CAP_S,
        )
        logger.info("Reconnecting in %.1fs (attempt %d/%d)", delay, self._reconnect_attempts, self.MAX_RECONNECT)
        await asyncio.sleep(delay)
        await self._do_connect()
