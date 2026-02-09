"""
Text-to-Speech (TTS) Client

Converts text to audio with streaming support.
Supports multiple TTS backends: Qwen, Ollama, OpenAI, local models.
"""

import logging
import asyncio
from typing import Optional, AsyncIterator, Dict, Any, List
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


@dataclass
class TTSConfig:
    """TTS configuration."""
    sample_rate: int = 16000  # 16 kHz
    language: str = "en"  # Language code
    backend: str = "qwen"  # qwen, ollama, openai, local
    base_url: str = "http://127.0.0.1:8000"  # Service endpoint
    model: str = "qwen-tts"  # Model name
    voice: str = "default"  # Voice identifier
    speed: float = 1.0  # Speech speed (0.5-2.0)
    timeout: float = 30.0


class TTS:
    """Text-to-Speech engine."""

    def __init__(self, config: Optional[TTSConfig] = None):
        """
        Initialize TTS client.

        Args:
            config: TTS configuration
        """
        self.config = config or TTSConfig()
        self.client = None
        self._initialized = False
        self._current_request_id = None

    async def initialize(self) -> None:
        """Initialize TTS service."""
        try:
            self.client = httpx.AsyncClient(timeout=self.config.timeout)
            
            # Verify service availability
            if self.config.backend == "qwen":
                try:
                    response = await self.client.get(
                        f"{self.config.base_url}/v1/models",
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        self._initialized = True
                except Exception as e:
                    logger.warning(f"Qwen TTS unavailable: {e}")
            else:
                self._initialized = True
            
            logger.info(f"TTS initialized (backend: {self.config.backend})")
        except Exception as e:
            logger.error(f"TTS initialization failed: {e}")

    async def synthesize(
        self,
        text: str,
        streaming: bool = True,
    ) -> Dict[str, Any]:
        """
        Synthesize text to audio.

        Args:
            text: Text to speak
            streaming: Return audio chunks for streaming

        Returns:
            {"audio": bytes, "duration_ms": 1500, "streaming": False}
            or async iterator of audio chunks if streaming=True
        """
        if not self._initialized:
            logger.warning("TTS not initialized")
            return {"audio": b"", "duration_ms": 0, "streaming": False}

        try:
            if self.config.backend == "qwen":
                return await self._synthesize_qwen(text, streaming)
            elif self.config.backend == "ollama":
                return await self._synthesize_ollama(text, streaming)
            elif self.config.backend == "openai":
                return await self._synthesize_openai(text, streaming)
            else:
                return {"audio": b"", "duration_ms": 0, "streaming": False}

        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            return {"audio": b"", "duration_ms": 0, "streaming": False, "error": str(e)}

    async def _synthesize_qwen(
        self,
        text: str,
        streaming: bool = True,
    ) -> Dict[str, Any]:
        """Synthesize using Qwen TTS."""
        try:
            payload = {
                "text": text,
                "language": self.config.language,
                "voice": self.config.voice,
                "speed": self.config.speed,
                "streaming": streaming,
            }

            response = await self.client.post(
                f"{self.config.base_url}/v1/audio/speech",
                json=payload,
                timeout=self.config.timeout,
            )

            if response.status_code == 200:
                audio = response.content
                # Estimate duration: ~100 words/min = 0.6s per word
                word_count = len(text.split())
                duration_ms = int((word_count / 150) * 1000 / self.config.speed)
                
                return {
                    "audio": audio,
                    "duration_ms": duration_ms,
                    "streaming": False,
                }
            else:
                logger.error(f"Qwen TTS error: {response.status_code}")
                return {"audio": b"", "duration_ms": 0, "streaming": False}

        except asyncio.TimeoutError:
            logger.error("Qwen TTS timeout")
            return {"audio": b"", "duration_ms": 0, "streaming": False, "timeout": True}
        except Exception as e:
            logger.error(f"Qwen synthesis failed: {e}")
            return {"audio": b"", "duration_ms": 0, "streaming": False}

    async def _synthesize_ollama(
        self,
        text: str,
        streaming: bool = True,
    ) -> Dict[str, Any]:
        """Synthesize using Ollama TTS."""
        try:
            payload = {
                "text": text,
                "model": self.config.model,
                "stream": streaming,
            }

            response = await self.client.post(
                f"{self.config.base_url}/api/generate",
                json=payload,
                timeout=self.config.timeout,
            )

            if response.status_code == 200:
                audio = response.content
                word_count = len(text.split())
                duration_ms = int((word_count / 150) * 1000 / self.config.speed)
                
                return {
                    "audio": audio,
                    "duration_ms": duration_ms,
                    "streaming": False,
                }
            else:
                return {"audio": b"", "duration_ms": 0, "streaming": False}

        except Exception as e:
            logger.error(f"Ollama synthesis failed: {e}")
            return {"audio": b"", "duration_ms": 0, "streaming": False}

    async def _synthesize_openai(
        self,
        text: str,
        streaming: bool = True,
    ) -> Dict[str, Any]:
        """Synthesize using OpenAI TTS API."""
        try:
            payload = {
                "model": "tts-1",
                "input": text,
                "voice": self.config.voice,
                "speed": self.config.speed,
            }

            response = await self.client.post(
                "https://api.openai.com/v1/audio/speech",
                json=payload,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=self.config.timeout,
            )

            if response.status_code == 200:
                audio = response.content
                word_count = len(text.split())
                duration_ms = int((word_count / 150) * 1000 / self.config.speed)
                
                return {
                    "audio": audio,
                    "duration_ms": duration_ms,
                    "streaming": False,
                }
            else:
                return {"audio": b"", "duration_ms": 0, "streaming": False}

        except Exception as e:
            logger.error(f"OpenAI synthesis failed: {e}")
            return {"audio": b"", "duration_ms": 0, "streaming": False}

    async def cancel_synthesis(self) -> None:
        """Cancel current synthesis request."""
        if self._current_request_id:
            logger.info(f"Cancelled synthesis: {self._current_request_id}")
            self._current_request_id = None

    async def shutdown(self) -> None:
        """Shutdown TTS client."""
        if self.client:
            await self.client.aclose()
            logger.info("TTS shutdown")
