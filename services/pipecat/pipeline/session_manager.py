"""
Session Manager for Voice Streaming

Manages voice session state, audio buffers, and conversation flow.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime
from uuid import uuid4

from .vad import VAD, VADConfig
from .asr import ASR, ASRConfig
from .tts import TTS, TTSConfig

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Voice session state."""
    session_id: str
    user_id: str
    created_at: str
    last_activity: str
    audio_buffer: bytearray = field(default_factory=bytearray)
    transcript: str = ""
    is_speaking_user: bool = False
    is_speaking_assistant: bool = False
    turn_count: int = 0
    interrupted: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionManager:
    """Manages voice streaming sessions."""

    def __init__(
        self,
        vad_config: Optional[VADConfig] = None,
        asr_config: Optional[ASRConfig] = None,
        tts_config: Optional[TTSConfig] = None,
    ):
        """
        Initialize session manager.

        Args:
            vad_config: Voice Activity Detection config
            asr_config: Automatic Speech Recognition config
            tts_config: Text-to-Speech config
        """
        self.vad = VAD(vad_config or VADConfig())
        self.asr = ASR(asr_config or ASRConfig())
        self.tts = TTS(tts_config or TTSConfig())
        self.sessions: Dict[str, SessionState] = {}
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all pipeline components."""
        try:
            await self.vad.initialize()
            await self.asr.initialize()
            await self.tts.initialize()
            self._initialized = True
            logger.info("Session manager initialized")
        except Exception as e:
            logger.error(f"Session manager init failed: {e}")
            self._initialized = False

    def create_session(self, user_id: str) -> str:
        """
        Create new voice session.

        Args:
            user_id: User identifier

        Returns:
            session_id
        """
        session_id = str(uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        
        state = SessionState(
            session_id=session_id,
            user_id=user_id,
            created_at=now,
            last_activity=now,
        )
        
        self.sessions[session_id] = state
        logger.info(f"Created session {session_id} for user {user_id}")
        return session_id

    def get_session(self, session_id: str) -> Optional[SessionState]:
        """Get session state."""
        return self.sessions.get(session_id)

    def end_session(self, session_id: str) -> None:
        """End voice session."""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            duration_s = 0  # Calculate from timestamps
            logger.info(
                f"Ended session {session_id}: "
                f"{session.turn_count} turns, {duration_s}s"
            )
            del self.sessions[session_id]

    async def process_audio(
        self,
        session_id: str,
        audio_frame: bytes,
    ) -> Dict[str, Any]:
        """
        Process incoming audio frame.

        Args:
            session_id: Session identifier
            audio_frame: Audio data (16-bit PCM)

        Returns:
            Event dict with type, data, partial_transcript, etc.
        """
        session = self.get_session(session_id)
        if not session:
            logger.error(f"Unknown session {session_id}")
            return {"type": "error", "data": "Session not found"}

        try:
            # Add to buffer
            session.audio_buffer.extend(audio_frame)
            session.last_activity = datetime.utcnow().isoformat() + "Z"

            # Detect speech
            is_speech, confidence = self.vad.process_frame(audio_frame)

            event = {
                "type": "audio_frame",
                "session_id": session_id,
                "is_speech": is_speech,
                "confidence": confidence,
            }

            # Check if turn should end
            if self.vad.should_end_turn():
                event["type"] = "turn_complete"
                
                # Transcribe buffer
                if session.audio_buffer:
                    transcript_result = await self.asr.transcribe(
                        bytes(session.audio_buffer)
                    )
                    session.transcript = transcript_result.get("text", "")
                    event["transcript"] = session.transcript
                    
                    # Reset buffer and VAD
                    session.audio_buffer.clear()
                    self.vad.reset()
                    session.turn_count += 1

            return event

        except Exception as e:
            logger.error(f"Audio processing failed: {e}")
            return {"type": "error", "data": str(e)}

    async def synthesize_response(
        self,
        session_id: str,
        response_text: str,
    ) -> Dict[str, Any]:
        """
        Synthesize text response to audio.

        Args:
            session_id: Session identifier
            response_text: Text to synthesize

        Returns:
            Audio data and metadata
        """
        session = self.get_session(session_id)
        if not session:
            return {"type": "error", "data": "Session not found"}

        try:
            session.is_speaking_assistant = True
            
            result = await self.tts.synthesize(response_text, streaming=True)
            
            return {
                "type": "audio_response",
                "session_id": session_id,
                "audio": result.get("audio"),
                "duration_ms": result.get("duration_ms", 0),
            }

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return {"type": "error", "data": str(e)}
        finally:
            session.is_speaking_assistant = False

    def interrupt_synthesis(self, session_id: str) -> None:
        """
        Interrupt assistant's speech (barge-in).

        Args:
            session_id: Session identifier
        """
        session = self.get_session(session_id)
        if session:
            session.interrupted = True
            logger.info(f"Interrupted synthesis for session {session_id}")

    async def shutdown(self) -> None:
        """Shutdown all components."""
        try:
            await self.vad.shutdown()
            await self.asr.shutdown()
            await self.tts.shutdown()
            logger.info("Session manager shutdown")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
