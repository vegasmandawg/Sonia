"""
Streaming Response Engine

Implements SSE (Server-Sent Events) and WebSocket streaming for real-time responses.
Supports streaming text, intermediate results, and metadata updates.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Dict, Any, Optional
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger(__name__)


class StreamingResponse:
    """Manages streaming responses to clients."""

    def __init__(self, request_id: Optional[str] = None):
        """
        Initialize streaming response.

        Args:
            request_id: Unique request identifier (auto-generated if None)
        """
        self.request_id = request_id or str(uuid4())
        self.events: list = []
        self._started = False

    async def stream_sse(self) -> AsyncIterator[str]:
        """
        Stream response as Server-Sent Events (SSE).

        Yields SSE-formatted messages for streaming to browser.

        Returns:
            Async iterator of SSE event strings
        """
        logger.info(f"Starting SSE stream: {self.request_id}")
        
        # Send stream start event
        yield self._format_sse({
            "type": "stream_start",
            "request_id": self.request_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        
        self._started = True

    async def add_text_chunk(self, chunk: str) -> str:
        """
        Add text chunk to stream.

        Args:
            chunk: Text to stream

        Returns:
            SSE formatted event
        """
        event = {
            "type": "text_chunk",
            "request_id": self.request_id,
            "data": chunk,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        logger.debug(f"Added text chunk: {len(chunk)} chars")
        
        return self._format_sse(event)

    async def add_thinking(self, thinking: str) -> str:
        """
        Add model's thinking/reasoning to stream.

        Args:
            thinking: Model's intermediate reasoning

        Returns:
            SSE formatted event
        """
        event = {
            "type": "thinking",
            "request_id": self.request_id,
            "data": thinking,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        return self._format_sse(event)

    async def add_tool_call(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> str:
        """
        Add tool call to stream.

        Args:
            tool_name: Name of tool being called
            tool_input: Input to tool

        Returns:
            SSE formatted event
        """
        event = {
            "type": "tool_call",
            "request_id": self.request_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        logger.info(f"Tool call: {tool_name}")
        
        return self._format_sse(event)

    async def add_tool_result(
        self,
        tool_name: str,
        result: Dict[str, Any],
        success: bool = True,
    ) -> str:
        """
        Add tool result to stream.

        Args:
            tool_name: Name of tool
            result: Result from tool
            success: If True, result is successful

        Returns:
            SSE formatted event
        """
        event = {
            "type": "tool_result",
            "request_id": self.request_id,
            "tool_name": tool_name,
            "result": result,
            "success": success,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        logger.info(f"Tool result: {tool_name}")
        
        return self._format_sse(event)

    async def add_metadata(self, key: str, value: Any) -> str:
        """
        Add metadata to stream.

        Args:
            key: Metadata key
            value: Metadata value

        Returns:
            SSE formatted event
        """
        event = {
            "type": "metadata",
            "request_id": self.request_id,
            "key": key,
            "value": value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        return self._format_sse(event)

    async def add_status(self, status: str, details: str = "") -> str:
        """
        Add status update to stream.

        Args:
            status: Status message
            details: Additional details

        Returns:
            SSE formatted event
        """
        event = {
            "type": "status",
            "request_id": self.request_id,
            "status": status,
            "details": details,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        return self._format_sse(event)

    async def stream_complete(
        self,
        final_response: str,
        total_tokens: int = 0,
    ) -> str:
        """
        Mark stream as complete.

        Args:
            final_response: Final response text
            total_tokens: Total tokens used

        Returns:
            SSE formatted completion event
        """
        event = {
            "type": "stream_complete",
            "request_id": self.request_id,
            "final_response": final_response,
            "total_tokens": total_tokens,
            "total_events": len(self.events),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        logger.info(f"Stream complete: {self.request_id}")
        
        return self._format_sse(event)

    async def stream_error(self, error: str) -> str:
        """
        Send error to stream.

        Args:
            error: Error message

        Returns:
            SSE formatted error event
        """
        event = {
            "type": "error",
            "request_id": self.request_id,
            "error": error,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        
        self.events.append(event)
        logger.error(f"Stream error: {error}")
        
        return self._format_sse(event)

    @staticmethod
    def _format_sse(event: Dict[str, Any]) -> str:
        """
        Format event as SSE message.

        Args:
            event: Event dictionary

        Returns:
            SSE formatted string (ready to send to client)
        """
        # SSE format: "data: {json}\n\n"
        data = json.dumps(event)
        return f"data: {data}\n\n"

    def get_events(self) -> list:
        """Get all events recorded so far."""
        return self.events.copy()

    async def shutdown(self) -> None:
        """Cleanup resources."""
        logger.debug(f"Stream shutdown: {self.request_id}")


class WebSocketStream:
    """WebSocket-based streaming for bidirectional communication."""

    def __init__(self, websocket, request_id: Optional[str] = None):
        """
        Initialize WebSocket stream.

        Args:
            websocket: FastAPI WebSocket connection
            request_id: Unique request identifier
        """
        self.websocket = websocket
        self.request_id = request_id or str(uuid4())
        self.events: list = []

    async def send_event(self, event: Dict[str, Any]) -> None:
        """
        Send event through WebSocket.

        Args:
            event: Event dictionary
        """
        try:
            await self.websocket.send_json(event)
            self.events.append(event)
        except Exception as e:
            logger.error(f"WebSocket send failed: {e}")
            raise

    async def send_text_chunk(self, chunk: str) -> None:
        """Send text chunk."""
        await self.send_event({
            "type": "text_chunk",
            "data": chunk,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def send_tool_call(self, tool_name: str, tool_input: Dict) -> None:
        """Send tool call event."""
        await self.send_event({
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def send_tool_result(self, tool_name: str, result: Dict) -> None:
        """Send tool result event."""
        await self.send_event({
            "type": "tool_result",
            "tool_name": tool_name,
            "result": result,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def send_status(self, status: str, details: str = "") -> None:
        """Send status update."""
        await self.send_event({
            "type": "status",
            "status": status,
            "details": details,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def send_complete(self, final_response: str) -> None:
        """Send completion event."""
        await self.send_event({
            "type": "complete",
            "final_response": final_response,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    async def send_error(self, error: str) -> None:
        """Send error event."""
        await self.send_event({
            "type": "error",
            "error": error,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
