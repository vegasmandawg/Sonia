"""
Pipecat Service
===============

Real-time voice and modality gateway for Sonia.
Handles audio streaming, VAD, ASR, TTS, and turn-taking.

Features:
- WebSocket streaming (audio, text, events)
- Voice Activity Detection (VAD)
- Automatic Speech Recognition (ASR)
- Text-to-Speech (TTS)
- Turn-taking and interruption handling
- Low-latency optimization (<200ms target)

Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "Sonia Team"
__license__ = "MIT"

import logging

logger = logging.getLogger(__name__)
logger.info(f"Pipecat v{__version__} initialized")
