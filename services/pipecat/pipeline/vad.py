"""
Voice Activity Detection (VAD) Module

Detects speech in audio stream with configurable sensitivity.
Supports multiple VAD backends: Silero VAD, WebRTC VAD, simple energy-based.
"""

import logging
import math
from typing import Optional, Tuple, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VADConfig:
    """VAD configuration."""
    sample_rate: int = 16000  # 16 kHz
    frame_size: int = 512  # 512 samples (32ms at 16kHz)
    threshold: float = 0.5  # Energy threshold (0-1)
    min_speech_duration: int = 100  # Min ms of speech
    min_silence_duration: int = 500  # Min ms of silence to end turn
    backend: str = "energy"  # energy, silero, webrtc


class VAD:
    """Voice Activity Detection engine."""

    def __init__(self, config: Optional[VADConfig] = None):
        """
        Initialize VAD.

        Args:
            config: VAD configuration
        """
        self.config = config or VADConfig()
        self.is_speech = False
        self.speech_start_time = None
        self.silence_start_time = None
        self.frame_count = 0
        self._silence_duration = 0
        self._speech_duration = 0

    async def initialize(self) -> None:
        """Initialize VAD backend."""
        try:
            if self.config.backend == "silero":
                await self._init_silero_vad()
            elif self.config.backend == "webrtc":
                await self._init_webrtc_vad()
            else:
                logger.info("Using energy-based VAD")
            
            logger.info(f"VAD initialized (backend: {self.config.backend})")
        except Exception as e:
            logger.warning(f"VAD init failed, using energy-based: {e}")
            self.config.backend = "energy"

    async def _init_silero_vad(self) -> None:
        """Initialize Silero VAD (requires torch)."""
        try:
            import silero_vad
            self.silero_model = silero_vad.load_silero_vad()
            logger.info("Silero VAD loaded")
        except ImportError:
            raise ImportError("silero-vad not installed")

    async def _init_webrtc_vad(self) -> None:
        """Initialize WebRTC VAD (requires py-webrtcvad)."""
        try:
            import webrtcvad
            self.webrtc_vad = webrtcvad.Vad(2)  # Aggressiveness: 0-3
            logger.info("WebRTC VAD loaded")
        except ImportError:
            raise ImportError("webrtcvad not installed")

    def process_frame(self, audio_bytes: bytes) -> Tuple[bool, float]:
        """
        Process audio frame for speech detection.

        Args:
            audio_bytes: Audio frame (typically 512 samples = 32ms at 16kHz)

        Returns:
            (is_speech, confidence) tuple
        """
        self.frame_count += 1

        try:
            if self.config.backend == "silero":
                return self._detect_silero(audio_bytes)
            elif self.config.backend == "webrtc":
                return self._detect_webrtc(audio_bytes)
            else:
                return self._detect_energy(audio_bytes)
        except Exception as e:
            logger.error(f"VAD detection failed: {e}")
            return False, 0.0

    def _detect_energy(self, audio_bytes: bytes) -> Tuple[bool, float]:
        """
        Simple energy-based speech detection.

        Computes RMS energy and thresholds.
        """
        # Convert bytes to samples (16-bit PCM)
        import struct
        samples = struct.unpack(f"{len(audio_bytes)//2}h", audio_bytes)
        
        # Compute RMS energy
        if len(samples) == 0:
            return False, 0.0
        
        rms = math.sqrt(sum(s**2 for s in samples) / len(samples))
        
        # Normalize to 0-1 (16-bit audio max is 32768)
        normalized_rms = min(1.0, rms / 32768.0)
        
        # Simple threshold
        is_speech = normalized_rms > self.config.threshold
        
        return is_speech, normalized_rms

    def _detect_silero(self, audio_bytes: bytes) -> Tuple[bool, float]:
        """Speech detection using Silero VAD."""
        try:
            import torch
            
            # Convert bytes to tensor
            import struct
            samples = struct.unpack(f"{len(audio_bytes)//2}h", audio_bytes)
            
            # Normalize to [-1, 1]
            audio_tensor = torch.tensor(
                [s / 32768.0 for s in samples],
                dtype=torch.float32
            )
            
            # Get speech probability
            speech_prob = self.silero_model(
                audio_tensor,
                self.config.sample_rate
            ).item()
            
            is_speech = speech_prob > self.config.threshold
            return is_speech, speech_prob
            
        except Exception as e:
            logger.error(f"Silero detection failed: {e}")
            return False, 0.0

    def _detect_webrtc(self, audio_bytes: bytes) -> Tuple[bool, float]:
        """Speech detection using WebRTC VAD."""
        try:
            # WebRTC VAD returns binary decision
            is_speech = self.webrtc_vad.is_speech(
                audio_bytes,
                self.config.sample_rate
            )
            
            # Estimate confidence based on energy
            import struct
            samples = struct.unpack(f"{len(audio_bytes)//2}h", audio_bytes)
            rms = math.sqrt(sum(s**2 for s in samples) / len(samples))
            confidence = min(1.0, rms / 32768.0)
            
            return is_speech, confidence
            
        except Exception as e:
            logger.error(f"WebRTC detection failed: {e}")
            return False, 0.0

    def get_speech_duration(self) -> int:
        """Get current speech duration in ms."""
        if self.is_speech and self.speech_start_time is not None:
            frame_ms = (self.config.frame_size / self.config.sample_rate) * 1000
            return int(self._speech_duration + (self.frame_count * frame_ms))
        return int(self._speech_duration)

    def get_silence_duration(self) -> int:
        """Get current silence duration in ms."""
        if not self.is_speech and self.silence_start_time is not None:
            frame_ms = (self.config.frame_size / self.config.sample_rate) * 1000
            return int(self._silence_duration + (self.frame_count * frame_ms))
        return int(self._silence_duration)

    def should_end_turn(self) -> bool:
        """
        Determine if turn should end.

        True if: sufficient speech followed by sufficient silence.
        """
        speech_dur = self.get_speech_duration()
        silence_dur = self.get_silence_duration()
        
        return (
            speech_dur >= self.config.min_speech_duration and
            silence_dur >= self.config.min_silence_duration
        )

    def reset(self) -> None:
        """Reset VAD state for new turn."""
        self.is_speech = False
        self.speech_start_time = None
        self.silence_start_time = None
        self.frame_count = 0
        self._silence_duration = 0
        self._speech_duration = 0
        logger.debug("VAD state reset")

    async def shutdown(self) -> None:
        """Shutdown VAD."""
        logger.info("VAD shutdown")
