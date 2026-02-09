"""
WebSocket Server for Voice Streaming

Handles real-time bidirectional audio streaming with clients.
Protocol: JSON messages with embedded audio frames.
"""

import logging
from typing import Set, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
import json
import base64

from ..pipeline.session_manager import SessionManager

logger = logging.getLogger(__name__)


class WebSocketServer:
    """WebSocket server for voice streaming."""

    def __init__(self, session_manager: SessionManager):
        """
        Initialize WebSocket server.

        Args:
            session_manager: Session manager instance
        """
        self.session_manager = session_manager
        self.connections: Dict[str, Set[WebSocket]] = {}  # session_id -> connections

    async def connect(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> None:
        """
        Accept WebSocket connection.

        Args:
            session_id: Session identifier
            websocket: WebSocket connection
        """
        try:
            await websocket.accept()
            
            if session_id not in self.connections:
                self.connections[session_id] = set()
            
            self.connections[session_id].add(websocket)
            logger.info(f"WebSocket connected: {session_id}")
            
            # Send connection confirmation
            await websocket.send_json({
                "type": "connected",
                "session_id": session_id,
                "message": "Connected to Pipecat voice service",
            })
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            raise

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """
        Disconnect WebSocket connection.

        Args:
            session_id: Session identifier
            websocket: WebSocket connection
        """
        try:
            if session_id in self.connections:
                self.connections[session_id].discard(websocket)
                
                if not self.connections[session_id]:
                    del self.connections[session_id]
                    self.session_manager.end_session(session_id)
            
            logger.info(f"WebSocket disconnected: {session_id}")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")

    async def receive_audio(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> bytes:
        """
        Receive audio frame from client.

        Args:
            session_id: Session identifier
            websocket: WebSocket connection

        Returns:
            Audio bytes
        """
        try:
            message = await websocket.receive_json()
            
            if message.get("type") == "audio":
                # Audio is base64-encoded in JSON
                audio_base64 = message.get("data", "")
                audio_bytes = base64.b64decode(audio_base64)
                return audio_bytes
            
            elif message.get("type") == "interrupt":
                self.session_manager.interrupt_synthesis(session_id)
                return b""
            
            else:
                logger.warning(f"Unknown message type: {message.get('type')}")
                return b""
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON in WebSocket message")
            return b""
        except Exception as e:
            logger.error(f"Receive error: {e}")
            return b""

    async def send_event(
        self,
        session_id: str,
        event: Dict[str, Any],
    ) -> None:
        """
        Send event to all clients in session.

        Args:
            session_id: Session identifier
            event: Event data
        """
        try:
            if session_id not in self.connections:
                logger.warning(f"No connections for session {session_id}")
                return
            
            # Send to all clients in session
            for websocket in self.connections[session_id]:
                try:
                    await websocket.send_json(event)
                except Exception as e:
                    logger.error(f"Send error: {e}")

        except Exception as e:
            logger.error(f"Broadcast error: {e}")

    async def send_audio(
        self,
        session_id: str,
        audio_bytes: bytes,
    ) -> None:
        """
        Send audio to client.

        Args:
            session_id: Session identifier
            audio_bytes: Audio data
        """
        try:
            # Base64 encode audio
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            
            event = {
                "type": "audio",
                "session_id": session_id,
                "data": audio_base64,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            
            await self.send_event(session_id, event)
            
        except Exception as e:
            logger.error(f"Audio send error: {e}")

    async def send_transcript(
        self,
        session_id: str,
        transcript: str,
        is_partial: bool = False,
    ) -> None:
        """
        Send transcript to client.

        Args:
            session_id: Session identifier
            transcript: Text transcript
            is_partial: If True, this is partial/interim transcript
        """
        try:
            event = {
                "type": "partial_transcript" if is_partial else "transcript",
                "session_id": session_id,
                "text": transcript,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            
            await self.send_event(session_id, event)
            
        except Exception as e:
            logger.error(f"Transcript send error: {e}")

    async def send_status(
        self,
        session_id: str,
        status: str,
        details: str = "",
    ) -> None:
        """
        Send status update to client.

        Args:
            session_id: Session identifier
            status: Status code (listening, processing, responding, etc.)
            details: Additional details
        """
        try:
            event = {
                "type": "status",
                "session_id": session_id,
                "status": status,
                "details": details,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            
            await self.send_event(session_id, event)
            
        except Exception as e:
            logger.error(f"Status send error: {e}")

    async def broadcast_turn_complete(
        self,
        session_id: str,
        transcript: str,
        confidence: float,
    ) -> None:
        """
        Broadcast turn completion event.

        Args:
            session_id: Session identifier
            transcript: User's transcript
            confidence: Confidence score (0-1)
        """
        try:
            event = {
                "type": "turn_complete",
                "session_id": session_id,
                "transcript": transcript,
                "confidence": confidence,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            
            await self.send_event(session_id, event)
            
        except Exception as e:
            logger.error(f"Turn complete broadcast error: {e}")


from datetime import datetime
