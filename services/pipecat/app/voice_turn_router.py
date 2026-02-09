"""
Voice Turn Router -- v2.8-m1

Bridges Pipecat's WebSocket handler to the gateway stream client.
Routes user text through the real turn pipeline:

  Pipecat WS -> GatewayStreamClient -> /v1/stream/{session_id}
    -> memory recall -> model chat -> tool exec -> memory write
    -> response.final -> Pipecat WS -> user

v2.8 additions:
  - Cancellation support: cancel_turn() aborts in-flight model calls
  - Barge-in handling: new turn auto-cancels previous turn
  - No zombie tasks: cancelled turns leave no orphaned async tasks

Event flow per user message:
  1. User sends text via Pipecat WS
  2. VoiceTurnRouter.process_turn() calls GatewayStreamClient.send_turn()
  3. Gateway processes through stream pipeline
  4. Response events collected (partial -> final)
  5. Final text returned to Pipecat WS handler
  6. Latency + telemetry emitted
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("pipecat.voice_turn_router")


@dataclass
class VoiceTurnRecord:
    """Record of a single voice turn through the full pipeline."""
    turn_id: str = ""
    session_id: str = ""
    correlation_id: str = ""
    user_text: str = ""
    assistant_text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    partial_count: int = 0
    latency_ms: float = 0.0
    gateway_latency_ms: float = 0.0
    ok: bool = False
    error: str = ""
    timestamp: float = 0.0


class VoiceTurnRouter:
    """
    Routes voice turns through the gateway stream pipeline.

    Manages per-session stream client lifecycle:
      - Lazy connect on first turn
      - Reconnect on failure
      - Cleanup on session end
    """

    def __init__(
        self,
        gateway_url: str = "http://127.0.0.1:7000",
        turn_timeout: float = 30.0,
        on_partial: Optional[Callable[[str, str], Coroutine]] = None,
    ):
        """
        Args:
            gateway_url: Base URL for the API gateway.
            turn_timeout: Max seconds to wait for a turn response.
            on_partial: Callback(session_id, partial_text) for streaming.
        """
        self.gateway_url = gateway_url
        self.turn_timeout = turn_timeout
        self.on_partial = on_partial

        # Session -> client mapping
        self._clients: Dict[str, Any] = {}  # session_id -> GatewayStreamClient
        self._lock = asyncio.Lock()
        self._turn_history: List[VoiceTurnRecord] = []
        self._max_history = 500

        # v2.8: Cancellation tracking per session
        self._active_tasks: Dict[str, asyncio.Task] = {}  # session_id -> active turn task
        self._cancelled_turns: List[str] = []  # turn_ids that were cancelled

    @property
    def active_sessions(self) -> int:
        return len(self._clients)

    @property
    def total_turns(self) -> int:
        return len(self._turn_history)

    async def process_turn(
        self,
        user_text: str,
        pipecat_session_id: str,
        correlation_id: str = "",
    ) -> VoiceTurnRecord:
        """
        Process a voice turn through the gateway stream pipeline.

        1. Get or create stream client for this session
        2. Send turn via WS stream
        3. Collect response
        4. Return VoiceTurnRecord with full telemetry

        Args:
            user_text: The user's text input
            pipecat_session_id: Pipecat's session ID (maps to a gateway session)
            correlation_id: Trace ID for this turn
        """
        if not correlation_id:
            correlation_id = f"req_{uuid.uuid4().hex[:12]}"

        t0 = time.monotonic()
        record = VoiceTurnRecord(
            turn_id=f"vturn_{uuid.uuid4().hex[:8]}",
            session_id=pipecat_session_id,
            correlation_id=correlation_id,
            user_text=user_text,
            timestamp=time.time(),
        )

        # v2.8: Cancel any previous active turn for this session (barge-in)
        prev_task = self._active_tasks.pop(pipecat_session_id, None)
        if prev_task is not None and not prev_task.done():
            prev_task.cancel()
            try:
                await prev_task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Barge-in: cancelled previous turn for session=%s", pipecat_session_id)

        # Register current task for cancellation
        self._active_tasks[pipecat_session_id] = asyncio.current_task()

        try:
            client = await self._get_or_create_client(pipecat_session_id)

            # Build partial callback scoped to this session
            async def _on_partial(text: str):
                record.partial_count += 1
                if self.on_partial:
                    await self.on_partial(pipecat_session_id, text)

            # Temporarily set partial callback
            old_partial = client.on_partial
            client.on_partial = _on_partial

            try:
                result = await client.send_turn(
                    text=user_text,
                    correlation_id=correlation_id,
                    timeout=self.turn_timeout,
                )
            finally:
                client.on_partial = old_partial

            record.ok = result.ok
            record.assistant_text = result.assistant_text
            record.tool_calls = result.tool_calls
            record.gateway_latency_ms = result.latency_ms
            record.error = result.error

        except asyncio.CancelledError:
            record.error = "Turn cancelled"
            self._cancelled_turns.append(record.turn_id)
            logger.info("Turn cancelled session=%s turn=%s", pipecat_session_id, record.turn_id)

        except Exception as e:
            record.error = f"Router error: {e}"
            logger.error(
                "Turn failed session=%s corr=%s: %s",
                pipecat_session_id, correlation_id, e,
            )

        finally:
            # v2.8: Unregister task -- no zombies
            self._active_tasks.pop(pipecat_session_id, None)

        record.latency_ms = (time.monotonic() - t0) * 1000

        # Record history
        self._turn_history.append(record)
        if len(self._turn_history) > self._max_history:
            self._turn_history = self._turn_history[-self._max_history:]

        logger.info(
            "Turn completed session=%s ok=%s latency=%.0fms text=%s",
            pipecat_session_id,
            record.ok,
            record.latency_ms,
            record.assistant_text[:80] if record.assistant_text else record.error[:80],
        )

        return record

    async def cancel_turn(self, pipecat_session_id: str, reason: str = "user_cancel") -> Optional[str]:
        """
        Cancel the active turn for a session.

        Returns the cancelled turn_id, or None if no active turn.
        This is deterministic: after cancel_turn returns, no zombie tasks remain.
        """
        task = self._active_tasks.pop(pipecat_session_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("Cancelled active turn for session=%s reason=%s", pipecat_session_id, reason)
            return pipecat_session_id
        return None

    @property
    def active_tasks_count(self) -> int:
        """Number of in-flight turn tasks across all sessions."""
        return sum(1 for t in self._active_tasks.values() if not t.done())

    async def close_session(self, pipecat_session_id: str) -> bool:
        """Close and cleanup a session's stream client."""
        async with self._lock:
            client = self._clients.pop(pipecat_session_id, None)
        if client:
            await client.close()
            logger.info("Closed stream client for session %s", pipecat_session_id)
            return True
        return False

    async def close_all(self) -> int:
        """Close all active stream clients."""
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        count = 0
        for client in clients:
            try:
                await client.close()
                count += 1
            except Exception as e:
                logger.warning("Error closing client: %s", e)
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Return router statistics."""
        recent = self._turn_history[-20:] if self._turn_history else []
        ok_turns = [r for r in recent if r.ok]
        return {
            "active_sessions": self.active_sessions,
            "total_turns": self.total_turns,
            "recent_success_rate": len(ok_turns) / len(recent) if recent else 0.0,
            "recent_avg_latency_ms": (
                sum(r.latency_ms for r in ok_turns) / len(ok_turns)
                if ok_turns else 0.0
            ),
        }

    # -- Internal --

    async def _get_or_create_client(self, pipecat_session_id: str):
        """Get existing client or create + connect a new one."""
        from clients.gateway_stream_client import GatewayStreamClient

        async with self._lock:
            if pipecat_session_id in self._clients:
                client = self._clients[pipecat_session_id]
                if client.state.value == "connected":
                    return client
                # Reconnect if disconnected
                try:
                    await client.connect()
                    return client
                except Exception:
                    pass  # Fall through to create new

            # Create new client
            client = GatewayStreamClient(
                gateway_url=self.gateway_url,
            )
            # Create gateway session + connect WS
            await client.create_session(
                user_id=f"pipecat-voice-{pipecat_session_id[:8]}",
            )
            await client.connect()
            self._clients[pipecat_session_id] = client
            return client
