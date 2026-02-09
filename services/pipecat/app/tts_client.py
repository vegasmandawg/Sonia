"""
Pipecat — Cancel-Aware TTS Client

Wraps the existing pipeline.tts.TTS with:
    - cancel_tts_evt awareness (checks between chunks and before start).
    - Turn state transition integration (THINKING → SPEAKING on first chunk).
    - Structured result with timing metadata.
    - Clean cancellation semantics (no orphan HTTP requests).

Usage:
    result = await synthesize_cancellable(session, text, tts, trace_id)
    if result["cancelled"]:
        # barge-in happened during synthesis
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.turn_taking import TurnState, transition
from app.session_manager import VoiceSession

logger = logging.getLogger(__name__)


async def synthesize_cancellable(
    session: VoiceSession,
    text: str,
    tts,  # pipeline.tts.TTS instance
    trace_id: str = "",
    state_transition: bool = True,
) -> Dict[str, Any]:
    """
    Run TTS synthesis with cancel-event awareness.

    Before starting synthesis, checks ``session.cancel_tts_evt``.
    If the event is set at any point, synthesis is aborted and
    ``{"cancelled": True}`` is returned.

    If *state_transition* is True and the session is currently in
    THINKING state, transitions to SPEAKING before synthesis begins.

    Args:
        session:          VoiceSession owning this turn.
        text:             Text to synthesize.
        tts:              Initialised TTS backend instance.
        trace_id:         Correlation ID.
        state_transition: Whether to attempt THINKING→SPEAKING transition.

    Returns:
        Dict with keys: audio, duration_ms, cancelled, cancel_reason,
        elapsed_ms, error.
    """
    t0 = time.monotonic()
    sid = session.session_id

    result: Dict[str, Any] = {
        "audio": b"",
        "duration_ms": 0,
        "cancelled": False,
        "cancel_reason": "",
        "elapsed_ms": 0,
        "error": None,
    }

    # ---- pre-flight cancel check ------------------------------------------
    if session.cancel_tts_evt.is_set():
        result["cancelled"] = True
        result["cancel_reason"] = "cancel_tts_evt set before start"
        logger.info(
            "tts_client: cancelled before start  session=%s  trace=%s",
            sid, trace_id,
        )
        return result

    # ---- state transition (THINKING → SPEAKING) ---------------------------
    if state_transition and session.turn_state == TurnState.THINKING:
        ok = await transition(
            session, TurnState.SPEAKING,
            reason="tts_start", trace_id=trace_id,
        )
        if not ok:
            result["error"] = "transition to SPEAKING failed"
            logger.warning(
                "tts_client: SPEAKING transition failed  session=%s  "
                "state=%s  trace=%s",
                sid, session.turn_state.value, trace_id,
            )
            return result

    # ---- run synthesis in a cancellable wrapper ---------------------------
    try:
        # Create the synthesis task
        synth_task = asyncio.create_task(
            tts.synthesize(text, streaming=True),
            name=f"tts_synth_{sid}",
        )
        session.register_task("tts_synth", synth_task)

        # Wait for either: synthesis completes OR cancel event fires
        cancel_waiter = asyncio.create_task(
            _wait_for_cancel(session.cancel_tts_evt),
            name=f"tts_cancel_wait_{sid}",
        )

        done, pending = await asyncio.wait(
            {synth_task, cancel_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # ---- cancel path -------------------------------------------------
        if cancel_waiter in done:
            # Cancel was signalled
            synth_task.cancel()
            try:
                await synth_task
            except asyncio.CancelledError:
                pass

            result["cancelled"] = True
            result["cancel_reason"] = "cancel_tts_evt during synthesis"
            logger.info(
                "tts_client: cancelled during synthesis  session=%s  "
                "elapsed=%.0fms  trace=%s",
                sid, (time.monotonic() - t0) * 1000, trace_id,
            )
        else:
            # Synthesis completed normally
            cancel_waiter.cancel()
            try:
                await cancel_waiter
            except asyncio.CancelledError:
                pass

            synth_result = synth_task.result()
            result["audio"] = synth_result.get("audio", b"")
            result["duration_ms"] = synth_result.get("duration_ms", 0)

            if synth_result.get("error"):
                result["error"] = synth_result["error"]

    except asyncio.CancelledError:
        result["cancelled"] = True
        result["cancel_reason"] = "task cancelled externally"
        logger.info(
            "tts_client: externally cancelled  session=%s  trace=%s",
            sid, trace_id,
        )
    except Exception as e:
        result["error"] = str(e)
        logger.error(
            "tts_client: synthesis error  session=%s  error=%s  trace=%s",
            sid, e, trace_id,
        )
    finally:
        session.unregister_task("tts_synth")
        result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)

    return result


async def _wait_for_cancel(evt: asyncio.Event) -> None:
    """Block until the cancel event is set."""
    await evt.wait()
