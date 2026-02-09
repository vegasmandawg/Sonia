"""
Pipecat — Watchdog-Wrapped ASR Client

Wraps the existing pipeline.asr.ASR with:
    - Watchdog timeout (configurable, default 10s).
    - Cancel-event awareness (abort on barge-in during decode).
    - Structured result with timing and error metadata.
    - Integration with the turn state machine (no direct state writes).

Usage:
    result = await transcribe_guarded(session, audio_bytes, asr, trace_id)
    if result.timed_out:
        # ASR took too long
    if result.cancelled:
        # Barge-in during ASR
    text = result.value["text"]
"""

import logging
import time
from typing import Any, Dict, Optional

from app.watchdog import run_with_timeout, WatchdogResult, StageTimeout
from app.session_manager import VoiceSession

logger = logging.getLogger(__name__)

# Default ASR decode timeout in seconds.
DEFAULT_ASR_TIMEOUT: float = 10.0


async def transcribe_guarded(
    session: VoiceSession,
    audio_bytes: bytes,
    asr,  # pipeline.asr.ASR instance
    trace_id: str = "",
    timeout_secs: float = DEFAULT_ASR_TIMEOUT,
    partial: bool = False,
) -> WatchdogResult:
    """
    Run ASR transcription under a watchdog timeout with cancel awareness.

    Wraps ``asr.transcribe(audio_bytes, partial)`` inside
    ``run_with_timeout`` so that:
        - If decode exceeds *timeout_secs*, it is aborted and
          ``result.timed_out`` is True.
        - If ``session.cancel_infer_evt`` fires (barge-in), decode is
          aborted and ``result.cancelled`` is True.
        - On normal completion, ``result.value`` contains the ASR dict
          (``{"text": ..., "confidence": ..., "partial": ...}``).

    Args:
        session:       VoiceSession owning this turn.
        audio_bytes:   Raw audio data (PCM 16-bit, 16 kHz).
        asr:           Initialised ASR backend instance.
        trace_id:      Correlation ID.
        timeout_secs:  Hard timeout for the decode stage.
        partial:       Whether to request partial results.

    Returns:
        WatchdogResult with value = ASR result dict on success.
    """
    sid = session.session_id

    logger.debug(
        "asr_client: starting transcribe  session=%s  "
        "audio_bytes=%d  timeout=%.1fs  trace=%s",
        sid, len(audio_bytes), timeout_secs, trace_id,
    )

    result = await run_with_timeout(
        coro=asr.transcribe(audio_bytes, partial=partial),
        timeout_secs=timeout_secs,
        stage_name="asr_decode",
        cancel_evt=session.cancel_infer_evt,
        raise_on_timeout=False,
        session_id=sid,
        trace_id=trace_id,
    )

    # Log outcome
    if result.timed_out:
        logger.warning(
            "asr_client: decode timed out  session=%s  "
            "elapsed=%.0fms  limit=%.0fs  trace=%s",
            sid, result.elapsed_ms, timeout_secs, trace_id,
        )
    elif result.cancelled:
        logger.info(
            "asr_client: decode cancelled (barge-in)  session=%s  "
            "elapsed=%.0fms  trace=%s",
            sid, result.elapsed_ms, trace_id,
        )
    elif result.error:
        logger.error(
            "asr_client: decode error  session=%s  error=%s  "
            "elapsed=%.0fms  trace=%s",
            sid, result.error, result.elapsed_ms, trace_id,
        )
    else:
        text = result.value.get("text", "") if result.value else ""
        conf = result.value.get("confidence", 0) if result.value else 0
        logger.info(
            "asr_client: decode OK  session=%s  text_len=%d  "
            "confidence=%.2f  elapsed=%.0fms  trace=%s",
            sid, len(text), conf, result.elapsed_ms, trace_id,
        )

    return result
