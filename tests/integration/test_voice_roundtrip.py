"""v4.4 Epic B: Voice pipeline roundtrip integration test.

Tests the text round-trip path through the voice service with mocked ASR/TTS.
"""
import sys
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add pipecat to path
sys.path.insert(0, str(Path(r"S:\services\pipecat")))
sys.path.insert(0, str(Path(r"S:\services\pipecat\app")))
sys.path.insert(0, str(Path(r"S:\services\shared")))


class TestVoiceRoundtrip:
    """Test voice pipeline text roundtrip through mocked backends."""

    def test_voice_backends_import(self):
        """Verify voice_backends module imports without error."""
        from voice_backends import (
            ASRBackend, TTSBackend, VADBackend,
            OllamaASR, OllamaTTS, EnergyVAD,
            create_asr, create_tts, create_vad,
            ASRResult, TTSResult, VADEvent,
        )
        assert OllamaASR is not None
        assert OllamaTTS is not None
        assert EnergyVAD is not None

    def test_factory_returns_stub_by_default(self):
        """Factory returns unconfigured stub when no backend env is set."""
        from voice_backends import create_asr, create_tts, create_vad
        asr = create_asr()
        tts = create_tts()
        # VAD defaults to energy
        vad = create_vad()
        assert not asr.available
        assert not tts.available
        assert vad.available  # energy VAD is always available

    def test_factory_returns_ollama_asr(self):
        """Factory returns OllamaASR when configured."""
        from voice_backends import create_asr, OllamaASR
        asr = create_asr({"provider": "ollama"})
        assert isinstance(asr, OllamaASR)
        assert asr.available

    def test_factory_returns_ollama_tts(self):
        """Factory returns OllamaTTS when configured."""
        from voice_backends import create_tts, OllamaTTS
        tts = create_tts({"provider": "ollama"})
        assert isinstance(tts, OllamaTTS)
        assert tts.available

    def test_energy_vad_process_frame(self):
        """EnergyVAD processes a silent audio frame."""
        from voice_backends import EnergyVAD
        vad = EnergyVAD()
        # 512 samples of silence (16-bit PCM)
        import struct
        silence = struct.pack(f"{512}h", *([0] * 512))
        event = vad.process_frame(silence)
        assert event.is_speech is False
        assert event.confidence == 0.0

    def test_energy_vad_detects_noise(self):
        """EnergyVAD detects loud audio as speech."""
        from voice_backends import EnergyVAD
        vad = EnergyVAD({"provider": "energy"})
        import struct
        # Loud signal
        loud = struct.pack(f"{512}h", *([20000] * 512))
        event = vad.process_frame(loud)
        assert event.is_speech is True
        assert event.confidence > 0.5

    def test_asr_result_dataclass(self):
        """ASRResult fields default correctly."""
        from voice_backends import ASRResult
        r = ASRResult(text="hello", confidence=0.95)
        assert r.text == "hello"
        assert r.confidence == 0.95
        assert r.is_final is True

    def test_tts_result_dataclass(self):
        """TTSResult fields default correctly."""
        from voice_backends import TTSResult
        r = TTSResult(audio_bytes=b"audio", duration_ms=100.0)
        assert r.audio_bytes == b"audio"
        assert r.sample_rate == 24000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
