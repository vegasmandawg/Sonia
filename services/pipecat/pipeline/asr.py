"""
Automatic Speech Recognition (ASR) Client

Converts audio to text with support for streaming and partial results.
Supports multiple ASR backends: Ollama Whisper, Qwen, OpenAI, local models.
"""

import logging
import asyncio
from typing import Optional, AsyncIterator, Dict, Any
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


@dataclass
class ASRConfig:
    """ASR configuration."""
    sample_rate: int = 16000  # 16 kHz
    language: str = "en"  # Language code
    backend: str = "qwen"  # qwen, ollama-whisper, openai, local
    base_url: str = "http://127.0.0.1:8000"  # Service endpoint
    model: str = "qwen-audio"  # Model name
    timeout: float = 30.0
    api_key: str = ""  # v4.4: Required for OpenAI backend


class ASR:
    """Automatic Speech Recognition engine."""

    def __init__(self, config: Optional[ASRConfig] = None):
        """
        Initialize ASR client.

        Args:
            config: ASR configuration
        """
        self.config = config or ASRConfig()
        self.client = None
        self._initialized = False
        self.partial_transcript = ""

    async def initialize(self) -> None:
        """Initialize ASR service."""
        try:
            self.client = httpx.AsyncClient(timeout=self.config.timeout)
            
            # Verify service availability
            if self.config.backend == "qwen":
                # Qwen ASR typically available at port 8000
                try:
                    response = await self.client.get(
                        f"{self.config.base_url}/v1/models",
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        self._initialized = True
                except Exception as e:
                    logger.warning(f"Qwen ASR unavailable: {e}")
            else:
                self._initialized = True
            
            logger.info(f"ASR initialized (backend: {self.config.backend})")
        except Exception as e:
            logger.error(f"ASR initialization failed: {e}")

    async def transcribe(
        self,
        audio_bytes: bytes,
        partial: bool = False,
    ) -> Dict[str, Any]:
        """
        Transcribe audio to text.

        Args:
            audio_bytes: Audio data (PCM 16-bit, 16kHz)
            partial: If True, return partial results (for streaming)

        Returns:
            {"text": "...", "confidence": 0.95, "partial": False}
        """
        if not self._initialized:
            logger.warning("ASR not initialized, returning empty transcript")
            return {"text": "", "confidence": 0.0, "partial": partial}

        try:
            if self.config.backend == "qwen":
                return await self._transcribe_qwen(audio_bytes, partial)
            elif self.config.backend == "ollama-whisper":
                return await self._transcribe_ollama(audio_bytes, partial)
            elif self.config.backend == "openai":
                return await self._transcribe_openai(audio_bytes, partial)
            else:
                return {"text": "", "confidence": 0.0, "partial": partial}

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return {"text": "", "confidence": 0.0, "partial": partial, "error": str(e)}

    async def _transcribe_qwen(
        self,
        audio_bytes: bytes,
        partial: bool = False,
    ) -> Dict[str, Any]:
        """Transcribe using Qwen ASR."""
        try:
            # Qwen ASR API format
            files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
            data = {
                "language": self.config.language,
                "streaming": "true" if partial else "false",
            }

            response = await self.client.post(
                f"{self.config.base_url}/v1/audio/transcriptions",
                files=files,
                data=data,
                timeout=10.0,
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "text": result.get("text", ""),
                    "confidence": result.get("confidence", 0.8),
                    "partial": partial,
                }
            else:
                logger.error(f"Qwen ASR error: {response.status_code}")
                return {"text": "", "confidence": 0.0, "partial": partial}

        except asyncio.TimeoutError:
            logger.error("Qwen ASR timeout")
            return {"text": "", "confidence": 0.0, "partial": partial, "timeout": True}
        except Exception as e:
            logger.error(f"Qwen transcription failed: {e}")
            return {"text": "", "confidence": 0.0, "partial": partial}

    async def _transcribe_ollama(
        self,
        audio_bytes: bytes,
        partial: bool = False,
    ) -> Dict[str, Any]:
        """Transcribe using Ollama Whisper."""
        try:
            # Ollama Whisper endpoint
            files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}

            response = await self.client.post(
                f"{self.config.base_url}/api/transcribe",
                files=files,
                timeout=20.0,
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "text": result.get("text", ""),
                    "confidence": 0.85,
                    "partial": partial,
                }
            else:
                return {"text": "", "confidence": 0.0, "partial": partial}

        except Exception as e:
            logger.error(f"Ollama Whisper transcription failed: {e}")
            return {"text": "", "confidence": 0.0, "partial": partial}

    async def _transcribe_openai(
        self,
        audio_bytes: bytes,
        partial: bool = False,
    ) -> Dict[str, Any]:
        """Transcribe using OpenAI Whisper API."""
        try:
            # OpenAI API format
            files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
            data = {"model": "whisper-1", "language": self.config.language}

            response = await self.client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                files=files,
                data=data,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=30.0,
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    "text": result.get("text", ""),
                    "confidence": 0.9,
                    "partial": partial,
                }
            else:
                return {"text": "", "confidence": 0.0, "partial": partial}

        except Exception as e:
            logger.error(f"OpenAI transcription failed: {e}")
            return {"text": "", "confidence": 0.0, "partial": partial}

    def update_partial(self, transcript: str) -> None:
        """Update partial transcript."""
        self.partial_transcript = transcript

    def get_partial(self) -> str:
        """Get current partial transcript."""
        return self.partial_transcript

    def clear_partial(self) -> None:
        """Clear partial transcript."""
        self.partial_transcript = ""

    async def shutdown(self) -> None:
        """Shutdown ASR client."""
        if self.client:
            await self.client.aclose()
            logger.info("ASR shutdown")
