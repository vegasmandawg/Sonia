"""
Pipecat — Stage Watchdog / Timeout Guard

Provides a generic ``run_with_timeout`` coroutine wrapper that:
    1. Enforces a hard wall-clock deadline on any async stage.
    2. Optionally checks a cancel event (early abort on barge-in).
    3. Raises ``StageTimeout`` if the deadline expires.
    4. Returns a ``WatchdogResult`` with timing metadata.

Usage:
    result = await run_with_timeout(
        coro=some_async_call(),
        timeout_secs=10.0,
        stage_name="asr_decode",
        cancel_evt=session.cancel_infer_evt,
    )
    if result.timed_out:
        ...
    if result.cancelled:
        ...
    value = result.value
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Coroutine, Optional

logger = logging.getLogger(__name__)


class StageTimeout(Exception):
    """Raised when a pipeline stage exceeds its watchdog deadline."""

    def __init__(self, stage: str, timeout_secs: float, elapsed_secs: float):
        self.stage = stage
        self.timeout_secs = timeout_secs
        self.elapsed_secs = elapsed_secs
        super().__init__(
            f"Stage '{stage}' timed out after {elapsed_secs:.1f}s "
            f"(limit {timeout_secs:.1f}s)"
        )


@dataclass
class WatchdogResult:
    """Outcome of a watchdog-guarded stage execution."""
    value: Any = None
    timed_out: bool = False
    cancelled: bool = False
    cancel_reason: str = ""
    elapsed_ms: float = 0.0
    stage: str = ""
    error: Optional[str] = None


async def run_with_timeout(
    coro: Coroutine,
    timeout_secs: float,
    stage_name: str = "unknown",
    cancel_evt: Optional[asyncio.Event] = None,
    raise_on_timeout: bool = False,
    session_id: str = "",
    trace_id: str = "",
) -> WatchdogResult:
    """
    Execute *coro* with a hard timeout and optional cancel-event check.

    Args:
        coro:              The coroutine to guard.
        timeout_secs:      Maximum wall-clock seconds before abort.
        stage_name:        Human-readable stage label (for logs/metrics).
        cancel_evt:        If provided, abort early when this event is set.
        raise_on_timeout:  If True, raise StageTimeout instead of returning
                           a WatchdogResult with timed_out=True.
        session_id:        For log correlation.
        trace_id:          For log correlation.

    Returns:
        WatchdogResult with the coroutine's return value (if it finished),
        or timeout/cancellation metadata.

    Raises:
        StageTimeout: Only if *raise_on_timeout* is True and the deadline
                      expires.
    """
    t0 = time.monotonic()
    result = WatchdogResult(stage=stage_name)

    task = asyncio.create_task(coro, name=f"wd_{stage_name}_{session_id}")

    waiters = {task}
    cancel_task: Optional[asyncio.Task] = None

    if cancel_evt is not None:
        cancel_task = asyncio.create_task(
            _wait_for_event(cancel_evt),
            name=f"wd_cancel_{stage_name}_{session_id}",
        )
        waiters.add(cancel_task)

    try:
        done, pending = await asyncio.wait(
            waiters,
            timeout=timeout_secs,
            return_when=asyncio.FIRST_COMPLETED,
        )

        elapsed = time.monotonic() - t0

        # ---- timeout (nothing completed) ----------------------------------
        if not done:
            task.cancel()
            if cancel_task:
                cancel_task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            result.timed_out = True
            result.elapsed_ms = round(elapsed * 1000, 1)

            logger.warning(
                "watchdog TIMEOUT  stage=%s  session=%s  "
                "elapsed=%.0fms  limit=%.0fms  trace=%s",
                stage_name, session_id,
                elapsed * 1000, timeout_secs * 1000, trace_id,
            )

            if raise_on_timeout:
                raise StageTimeout(stage_name, timeout_secs, elapsed)

            return result

        # ---- cancel event fired -------------------------------------------
        if cancel_task and cancel_task in done:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            result.cancelled = True
            result.cancel_reason = f"cancel_evt during {stage_name}"
            result.elapsed_ms = round(elapsed * 1000, 1)

            logger.info(
                "watchdog CANCELLED  stage=%s  session=%s  "
                "elapsed=%.0fms  trace=%s",
                stage_name, session_id,
                elapsed * 1000, trace_id,
            )
            return result

        # ---- normal completion --------------------------------------------
        if cancel_task and cancel_task not in done:
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass

        # Retrieve result (may raise if the coro raised)
        try:
            result.value = task.result()
        except Exception as e:
            result.error = str(e)
            logger.error(
                "watchdog ERROR  stage=%s  session=%s  "
                "error=%s  elapsed=%.0fms  trace=%s",
                stage_name, session_id, e,
                elapsed * 1000, trace_id,
            )

        result.elapsed_ms = round(elapsed * 1000, 1)
        return result

    except asyncio.CancelledError:
        # Our own parent was cancelled
        task.cancel()
        if cancel_task:
            cancel_task.cancel()
        raise


async def _wait_for_event(evt: asyncio.Event) -> None:
    """Block until the event is set."""
    await evt.wait()
