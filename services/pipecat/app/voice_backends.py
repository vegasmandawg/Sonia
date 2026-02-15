"""Voice backend stubs for Pipecat ASR/TTS/VAD integration.

These define the interface contracts. Real implementations will be
plugged in when specific providers (Whisper, Coqui, Silero, etc.)
are configured.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("pipecat.voice_backends")


@dataclass
class ASRResult:
    """Result from speech-to-text transcription."""
    text: str = ""
    confidence: float = 0.0
    language: str = "en"
    duration_ms: float = 0.0
    is_final: bool = True


@dataclass
class TTSResult:
    """Result from text-to-speech synthesis."""
    audio_bytes: bytes = b""
    sample_rate: int = 24000
    channels: int = 1
    format: str = "pcm_s16le"
    duration_ms: float = 0.0


@dataclass
class VADEvent:
    """Voice activity detection event."""
    is_speech: bool = False
    confidence: float = 0.0
    start_ms: float = 0.0
    end_ms: float = 0.0


class ASRBackend:
    """Abstract ASR backend interface."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.provider = self.config.get("provider", "none")
        self._configured = self.provider != "none"

    @property
    def available(self) -> bool:
        return self._configured

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> ASRResult:
        """Transcribe audio bytes to text."""
        if not self._configured:
            logger.debug("ASR not configured, returning empty result")
            return ASRResult()
        raise NotImplementedError(f"ASR provider '{self.provider}' not implemented")

    async def transcribe_stream(self, audio_chunk: bytes) -> Optional[ASRResult]:
        """Process a streaming audio chunk. Returns partial/final results."""
        if not self._configured:
            return None
        raise NotImplementedError(f"ASR streaming for '{self.provider}' not implemented")


class TTSBackend:
    """Abstract TTS backend interface."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.provider = self.config.get("provider", "none")
        self._configured = self.provider != "none"

    @property
    def available(self) -> bool:
        return self._configured

    async def synthesize(self, text: str, voice: str = "default") -> TTSResult:
        """Synthesize text to audio."""
        if not self._configured:
            logger.debug("TTS not configured, returning empty result")
            return TTSResult()
        raise NotImplementedError(f"TTS provider '{self.provider}' not implemented")


class VADBackend:
    """Abstract VAD backend interface."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.provider = self.config.get("provider", "none")
        self._configured = self.provider != "none"

    @property
    def available(self) -> bool:
        return self._configured

    def process_frame(self, audio_frame: bytes, sample_rate: int = 16000) -> VADEvent:
        """Process an audio frame for voice activity."""
        if not self._configured:
            return VADEvent()
        raise NotImplementedError(f"VAD provider '{self.provider}' not implemented")


# Factory functions
def create_asr(config: Optional[Dict[str, Any]] = None) -> ASRBackend:
    """Create ASR backend from config."""
    return ASRBackend(config)

def create_tts(config: Optional[Dict[str, Any]] = None) -> TTSBackend:
    """Create TTS backend from config."""
    return TTSBackend(config)

def create_vad(config: Optional[Dict[str, Any]] = None) -> VADBackend:
    """Create VAD backend from config."""
    return VADBackend(config)
