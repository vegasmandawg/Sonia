"""
Pipecat FastAPI Service

Real-time voice and modality gateway for Sonia.
Exposes WebSocket endpoint for voice streaming.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse
from datetime import datetime

from .pipeline.session_manager import SessionManager, VADConfig, ASRConfig, TTSConfig
from .websocket.server import WebSocketServer

logger = logging.getLogger(__name__)


class PipecatService:
    """FastAPI service for voice streaming."""

    def __init__(self):
        """Initialize Pipecat service."""
        # Initialize pipeline components
        vad_config = VADConfig(
            sample_rate=16000,
            frame_size=512,
            threshold=0.5,
            min_speech_duration=100,
            min_silence_duration=500,
            backend="energy",  # Use energy-based VAD by default
        )
        
        asr_config = ASRConfig(
            sample_rate=16000,
            language="en",
            backend="qwen",
            base_url="http://127.0.0.1:8000",
            model="qwen-audio",
            timeout=30.0,
        )
        
        tts_config = TTSConfig(
            sample_rate=16000,
            language="en",
            backend="qwen",
            base_url="http://127.0.0.1:8000",
            model="qwen-tts",
            voice="default",
            speed=1.0,
            timeout=30.0,
        )
        
        self.session_manager = SessionManager(vad_config, asr_config, tts_config)
        self.websocket_server = WebSocketServer(self.session_manager)
        self.app = FastAPI(title="Sonia Pipecat Service", version="1.0.0")
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""

        @self.app.on_event("startup")
        async def startup():
            """Initialize service on startup."""
            logger.info("Pipecat service starting...")
            await self.session_manager.initialize()
            logger.info("Pipecat service ready")

        @self.app.on_event("shutdown")
        async def shutdown():
            """Shutdown service gracefully."""
            logger.info("Pipecat service shutting down...")
            await self.session_manager.shutdown()
            logger.info("Pipecat service stopped")

        @self.app.get("/health")
        async def health():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "service": "pipecat",
                "version": "1.0.0",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        @self.app.get("/status")
        async def status():
            """Status endpoint."""
            return {
                "service": "pipecat",
                "version": "1.0.0",
                "status": "running",
                "active_sessions": len(self.session_manager.sessions),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        @self.app.post("/api/v1/session/create")
        async def create_session(user_id: str = Query(...)):
            """Create new voice session."""
            try:
                session_id = self.session_manager.create_session(user_id)
                return {
                    "session_id": session_id,
                    "user_id": user_id,
                    "status": "created",
                }
            except Exception as e:
                logger.error(f"Session creation failed: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e)},
                )

        @self.app.websocket("/stream/{session_id}")
        async def websocket_endpoint(
            websocket: WebSocket,
            session_id: str,
        ):
            """WebSocket streaming endpoint for audio."""
            try:
                # Connect WebSocket
                await self.websocket_server.connect(session_id, websocket)
                
                # Create session if not exists
                if not self.session_manager.get_session(session_id):
                    user_id = f"user-{session_id[:8]}"
                    self.session_manager.create_session(user_id)

                # Main loop: receive audio, process, send events
                while True:
                    # Receive audio from client
                    audio_bytes = await self.websocket_server.receive_audio(
                        session_id, websocket
                    )
                    
                    if not audio_bytes:
                        continue

                    # Process audio through VAD/ASR/TTS pipeline
                    event = await self.session_manager.process_audio(
                        session_id, audio_bytes
                    )
                    
                    # Send event back to client
                    await self.websocket_server.send_event(session_id, event)
                    
                    # If turn complete, send full transcript
                    if event.get("type") == "turn_complete":
                        transcript = event.get("transcript", "")
                        await self.websocket_server.broadcast_turn_complete(
                            session_id,
                            transcript,
                            0.85,  # Confidence estimate
                        )

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected: {session_id}")
                await self.websocket_server.disconnect(session_id, websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await self.websocket_server.disconnect(session_id, websocket)

        @self.app.post("/api/v1/session/{session_id}/interrupt")
        async def interrupt_session(session_id: str):
            """Interrupt current synthesis (barge-in)."""
            try:
                self.websocket_server.interrupt_synthesis(session_id)
                return {"status": "interrupted", "session_id": session_id}
            except Exception as e:
                return JSONResponse(
                    status_code=500,
                    content={"error": str(e)},
                )

        @self.app.get("/api/v1/session/{session_id}/info")
        async def get_session_info(session_id: str):
            """Get session information."""
            session = self.session_manager.get_session(session_id)
            
            if not session:
                return JSONResponse(
                    status_code=404,
                    content={"error": "Session not found"},
                )
            
            return {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "created_at": session.created_at,
                "last_activity": session.last_activity,
                "transcript": session.transcript,
                "turn_count": session.turn_count,
                "is_speaking_user": session.is_speaking_user,
                "is_speaking_assistant": session.is_speaking_assistant,
            }


# Create service instance
pipecat_service = PipecatService()
app = pipecat_service.app
