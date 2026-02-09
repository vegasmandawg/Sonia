"""
Pipecat — Cancel-Aware Model Router Client

Wraps inference calls to the Model Router service (port 7010) with:
    - cancel_infer_evt awareness (abort if signalled).
    - Turn state transition integration (LISTENING → THINKING on call start).
    - Retry with backoff (inherits from existing API Gateway client pattern).
    - Structured result with timing and cancellation metadata.

Usage:
    result = await infer_cancellable(session, text, trace_id)
    if result["cancelled"]:
        # barge-in happened during inference
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.turn_taking import TurnState, transition
from app.session_manager import VoiceSession

logger = logging.getLogger(__name__)

# Model Router defaults
_MODEL_ROUTER_URL = "http://127.0.0.1:7010"
_INFER_TIMEOUT = 30.0
_RETRIES = 2
_BACKOFF = 1.5

# Module-level httpx client (created lazily)
_client: Optional[httpx.AsyncClient] = None


async def _get_client() -> httpx.AsyncClient:
    """Lazy-init a shared httpx.AsyncClient."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_INFER_TIMEOUT)
    return _client


async def close_client() -> None:
    """Shutdown the shared client (call on app shutdown)."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def infer_cancellable(
    session: VoiceSession,
    text: str,
    trace_id: str = "",
    model: Optional[str] = None,
    base_url: str = _MODEL_ROUTER_URL,
    timeout: float = _INFER_TIMEOUT,
    state_transition: bool = True,
) -> Dict[str, Any]:
    """
    Send an inference request to Model Router with cancel-event awareness.

    Before starting the request, checks ``session.cancel_infer_evt``.
    If the event fires during the HTTP call, the request is cancelled
    and ``{"cancelled": True}`` is returned.

    If *state_transition* is True and the session is in LISTENING state,
    transitions to THINKING before making the call.

    Args:
        session:          VoiceSession owning this turn.
        text:             User utterance / prompt text.
        trace_id:         Correlation ID.
        model:            Optional model override.
        base_url:         Model Router base URL.
        timeout:          HTTP timeout seconds.
        state_transition: Whether to attempt LISTENING→THINKING transition.

    Returns:
        Dict with keys: response, cancelled, cancel_reason, elapsed_ms, error.
    """
    t0 = time.monotonic()
    sid = session.session_id

    result: Dict[str, Any] = {
        "response": "",
        "cancelled": False,
        "cancel_reason": "",
        "elapsed_ms": 0,
        "error": None,
    }

    # ---- pre-flight cancel check ------------------------------------------
    if session.cancel_infer_evt.is_set():
        result["cancelled"] = True
        result["cancel_reason"] = "cancel_infer_evt set before start"
        logger.info(
            "model_router: cancelled before start  session=%s  trace=%s",
            sid, trace_id,
        )
        return result

    # ---- state transition (LISTENING → THINKING) --------------------------
    if state_transition and session.turn_state == TurnState.LISTENING:
        ok = await transition(
            session, TurnState.THINKING,
            reason="infer_start", trace_id=trace_id,
        )
        if not ok:
            result["error"] = "transition to THINKING failed"
            logger.warning(
                "model_router: THINKING transition failed  session=%s  "
                "state=%s  trace=%s",
                sid, session.turn_state.value, trace_id,
            )
            return result

    # ---- build request ----------------------------------------------------
    client = await _get_client()

    payload: Dict[str, Any] = {
        "message": text,
        "session_id": sid,
    }
    if model:
        payload["model"] = model

    headers = {
        "X-Correlation-ID": trace_id or sid,
        "X-Session-ID": sid,
    }

    # ---- run inference in a cancellable wrapper ---------------------------
    try:
        infer_task = asyncio.create_task(
            _do_infer(client, base_url, payload, headers, timeout),
            name=f"infer_{sid}",
        )
        session.register_task("infer", infer_task)

        cancel_waiter = asyncio.create_task(
            _wait_for_cancel(session.cancel_infer_evt),
            name=f"infer_cancel_wait_{sid}",
        )

        done, pending = await asyncio.wait(
            {infer_task, cancel_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # ---- cancel path -------------------------------------------------
        if cancel_waiter in done:
            infer_task.cancel()
            try:
                await infer_task
            except asyncio.CancelledError:
                pass

            result["cancelled"] = True
            result["cancel_reason"] = "cancel_infer_evt during inference"
            logger.info(
                "model_router: cancelled during inference  session=%s  "
                "elapsed=%.0fms  trace=%s",
                sid, (time.monotonic() - t0) * 1000, trace_id,
            )
        else:
            # Inference completed
            cancel_waiter.cancel()
            try:
                await cancel_waiter
            except asyncio.CancelledError:
                pass

            infer_result = infer_task.result()
            result["response"] = infer_result.get("response", "")
            if infer_result.get("error"):
                result["error"] = infer_result["error"]

    except asyncio.CancelledError:
        result["cancelled"] = True
        result["cancel_reason"] = "task cancelled externally"
    except Exception as e:
        result["error"] = str(e)
        logger.error(
            "model_router: inference error  session=%s  error=%s  trace=%s",
            sid, e, trace_id,
        )
    finally:
        session.unregister_task("infer")
        result["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)

    return result


async def _do_infer(
    client: httpx.AsyncClient,
    base_url: str,
    payload: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    """
    Execute the HTTP inference call with retry.

    Returns dict with "response" and optional "error" keys.
    """
    last_err: Optional[str] = None

    for attempt in range(_RETRIES):
        try:
            resp = await client.post(
                f"{base_url}/v1/chat",
                json=payload,
                headers=headers,
                timeout=timeout,
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok") and data.get("data"):
                    return {"response": data["data"].get("response", "")}
                # Non-ok envelope
                err = data.get("error", {})
                return {
                    "response": "",
                    "error": f"{err.get('code', 'UNKNOWN')}: "
                             f"{err.get('message', 'unknown')}",
                }

            # 4xx — don't retry
            if 400 <= resp.status_code < 500:
                return {
                    "response": "",
                    "error": f"HTTP {resp.status_code}",
                }

            # 5xx — retry
            last_err = f"HTTP {resp.status_code}"

        except httpx.TimeoutException:
            last_err = "timeout"
        except httpx.RequestError as e:
            last_err = str(e)

        if attempt < _RETRIES - 1:
            await asyncio.sleep(_BACKOFF ** attempt)

    return {"response": "", "error": f"inference failed after retries: {last_err}"}


async def _wait_for_cancel(evt: asyncio.Event) -> None:
    """Block until the cancel event is set."""
    await evt.wait()
