"""Voice backend providers for Pipecat ASR/TTS/VAD integration.

v4.4 Epic B: Concrete providers wired to pipeline/ modules.
Stubs remain as fallback when backends are not configured.
"""

import logging
import os
import struct
import math
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
        if not self._configured:
            logger.debug("ASR not configured, returning empty result")
            return ASRResult()
        raise NotImplementedError(f"ASR provider '{self.provider}' not implemented")

    async def transcribe_stream(self, audio_chunk: bytes) -> Optional[ASRResult]:
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
        if not self._configured:
            return VADEvent()
        raise NotImplementedError(f"VAD provider '{self.provider}' not implemented")


# ============================================================================
# v4.4 Epic B: Concrete Providers
# ============================================================================

class OllamaASR(ASRBackend):
    """ASR provider delegating to pipeline/asr.py Ollama Whisper backend."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        cfg.setdefault("provider", "ollama")
        super().__init__(cfg)
        self._asr = None

    async def _ensure_asr(self):
        if self._asr is None:
            import sys
            from pathlib import Path
            pipeline_dir = str(Path(__file__).resolve().parent.parent / "pipeline")
            if pipeline_dir not in sys.path:
                sys.path.insert(0, pipeline_dir)
            from asr import ASR, ASRConfig
            asr_cfg = ASRConfig(
                backend="ollama-whisper",
                base_url=self.config.get("base_url", "http://127.0.0.1:11434"),
            )
            self._asr = ASR(asr_cfg)
            await self._asr.initialize()

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> ASRResult:
        await self._ensure_asr()
        result = await self._asr.transcribe(audio_bytes, partial=False)
        return ASRResult(
            text=result.get("text", ""),
            confidence=result.get("confidence", 0.0),
            is_final=not result.get("partial", False),
        )


class QwenASR(ASRBackend):
    """ASR provider delegating to pipeline/asr.py Qwen backend."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        cfg.setdefault("provider", "qwen")
        super().__init__(cfg)
        self._asr = None

    async def _ensure_asr(self):
        if self._asr is None:
            import sys
            from pathlib import Path
            pipeline_dir = str(Path(__file__).resolve().parent.parent / "pipeline")
            if pipeline_dir not in sys.path:
                sys.path.insert(0, pipeline_dir)
            from asr import ASR, ASRConfig
            asr_cfg = ASRConfig(
                backend="qwen",
                base_url=self.config.get("base_url", "http://127.0.0.1:8000"),
            )
            self._asr = ASR(asr_cfg)
            await self._asr.initialize()

    async def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> ASRResult:
        await self._ensure_asr()
        result = await self._asr.transcribe(audio_bytes, partial=False)
        return ASRResult(
            text=result.get("text", ""),
            confidence=result.get("confidence", 0.0),
            is_final=not result.get("partial", False),
        )


class OllamaTTS(TTSBackend):
    """TTS provider delegating to pipeline/tts.py Ollama backend."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        cfg.setdefault("provider", "ollama")
        super().__init__(cfg)
        self._tts = None

    async def _ensure_tts(self):
        if self._tts is None:
            import sys
            from pathlib import Path
            pipeline_dir = str(Path(__file__).resolve().parent.parent / "pipeline")
            if pipeline_dir not in sys.path:
                sys.path.insert(0, pipeline_dir)
            from tts import TTS, TTSConfig
            tts_cfg = TTSConfig(
                backend="ollama",
                base_url=self.config.get("base_url", "http://127.0.0.1:11434"),
            )
            self._tts = TTS(tts_cfg)
            await self._tts.initialize()

    async def synthesize(self, text: str, voice: str = "default") -> TTSResult:
        await self._ensure_tts()
        result = await self._tts.synthesize(text, streaming=False)
        return TTSResult(
            audio_bytes=result.get("audio", b""),
            duration_ms=result.get("duration_ms", 0.0),
        )


class QwenTTS(TTSBackend):
    """TTS provider delegating to pipeline/tts.py Qwen backend."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        cfg.setdefault("provider", "qwen")
        super().__init__(cfg)
        self._tts = None

    async def _ensure_tts(self):
        if self._tts is None:
            import sys
            from pathlib import Path
            pipeline_dir = str(Path(__file__).resolve().parent.parent / "pipeline")
            if pipeline_dir not in sys.path:
                sys.path.insert(0, pipeline_dir)
            from tts import TTS, TTSConfig
            tts_cfg = TTSConfig(
                backend="qwen",
                base_url=self.config.get("base_url", "http://127.0.0.1:8000"),
            )
            self._tts = TTS(tts_cfg)
            await self._tts.initialize()

    async def synthesize(self, text: str, voice: str = "default") -> TTSResult:
        await self._ensure_tts()
        result = await self._tts.synthesize(text, streaming=False)
        return TTSResult(
            audio_bytes=result.get("audio", b""),
            duration_ms=result.get("duration_ms", 0.0),
        )


class EnergyVAD(VADBackend):
    """VAD provider delegating to pipeline/vad.py energy-based detection."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        cfg.setdefault("provider", "energy")
        super().__init__(cfg)
        self._vad = None

    def _ensure_vad(self):
        if self._vad is None:
            import sys
            from pathlib import Path
            pipeline_dir = str(Path(__file__).resolve().parent.parent / "pipeline")
            if pipeline_dir not in sys.path:
                sys.path.insert(0, pipeline_dir)
            from vad import VAD, VADConfig
            vad_cfg = VADConfig(backend="energy")
            self._vad = VAD(vad_cfg)

    def process_frame(self, audio_frame: bytes, sample_rate: int = 16000) -> VADEvent:
        self._ensure_vad()
        is_speech, confidence = self._vad.process_frame(audio_frame)
        return VADEvent(is_speech=is_speech, confidence=confidence)


# ============================================================================
# Factory functions with conditional provider selection
# ============================================================================

def create_asr(config: Optional[Dict[str, Any]] = None) -> ASRBackend:
    """Create ASR backend from config or env vars."""
    cfg = config or {}
    provider = cfg.get("provider") or os.environ.get("SONIA_ASR_BACKEND", "none")
    if provider == "ollama" or provider == "ollama-whisper":
        return OllamaASR(cfg)
    elif provider == "qwen":
        return QwenASR(cfg)
    else:
        return ASRBackend(cfg)


def create_tts(config: Optional[Dict[str, Any]] = None) -> TTSBackend:
    """Create TTS backend from config or env vars."""
    cfg = config or {}
    provider = cfg.get("provider") or os.environ.get("SONIA_TTS_BACKEND", "none")
    if provider == "ollama":
        return OllamaTTS(cfg)
    elif provider == "qwen":
        return QwenTTS(cfg)
    else:
        return TTSBackend(cfg)


def create_vad(config: Optional[Dict[str, Any]] = None) -> VADBackend:
    """Create VAD backend from config or env vars."""
    cfg = config or {}
    provider = cfg.get("provider") or os.environ.get("SONIA_VAD_BACKEND", "energy")
    if provider == "energy":
        return EnergyVAD(cfg)
    else:
        return VADBackend(cfg)
