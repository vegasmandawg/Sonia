"""
v2.8 Model Call Context -- Cancellable Model Routing

Wraps router_client.chat() calls with proper async cancellation support.
When a control.cancel event arrives mid-turn, the in-flight model call
is cancelled deterministically with no zombie tasks.

Usage:
    ctx = ModelCallContext(router_client)
    try:
        result = await ctx.call(messages, task_type="text")
    except ModelCallCancelled:
        # Turn was cancelled by user barge-in
        pass

    # Cancel from another coroutine:
    ctx.cancel(reason="user_barge_in")
"""

import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ModelCallCancelled(Exception):
    """Raised when a model call is cancelled via cancel()."""
    def __init__(self, reason: str = "cancelled"):
        self.reason = reason
        super().__init__(f"Model call cancelled: {reason}")


class ModelCallTimeout(Exception):
    """Raised when a model call exceeds its timeout."""
    def __init__(self, elapsed_ms: float, timeout_ms: float):
        self.elapsed_ms = elapsed_ms
        self.timeout_ms = timeout_ms
        super().__init__(f"Model call timed out: {elapsed_ms:.1f}ms > {timeout_ms:.1f}ms")


@dataclass
class ModelCallResult:
    """Result of a model call through the routing layer."""
    assistant_text: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    profile_used: str = ""
    fallback_used: bool = False
    cancelled: bool = False
    cancel_reason: str = ""
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None


class ModelCallContext:
    """
    Manages a single model call with cancellation support.

    Thread-safe: cancel() can be called from any coroutine while
    call() is in-flight. The in-flight task will be cancelled
    deterministically.

    One context per turn -- do NOT reuse across turns.
    """

    # Class-level tracking for zombie detection
    _active_contexts: int = 0
    _total_cancellations: int = 0

    def __init__(self, router_client, timeout_ms: float = 30000):
        self._router_client = router_client
        self._timeout_ms = timeout_ms
        self._task: Optional[asyncio.Task] = None
        self._cancelled = False
        self._cancel_reason = ""
        self._started_at: Optional[float] = None
        self._completed = False
        self._lock = asyncio.Lock()

    @property
    def is_active(self) -> bool:
        """True if a model call is currently in-flight."""
        return self._task is not None and not self._task.done()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_completed(self) -> bool:
        return self._completed

    async def call(
        self,
        messages: List[Dict[str, Any]],
        task_type: str = "text",
        model: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> ModelCallResult:
        """
        Execute a model call through the router with cancellation support.

        Raises:
            ModelCallCancelled: if cancel() was called before or during the call
            ModelCallTimeout: if the call exceeds timeout_ms
        """
        # Check pre-cancellation
        if self._cancelled:
            raise ModelCallCancelled(self._cancel_reason)

        self._started_at = time.monotonic()
        ModelCallContext._active_contexts += 1

        try:
            # Create the task so it can be cancelled externally
            self._task = asyncio.current_task()

            # Wrap with timeout
            timeout_s = self._timeout_ms / 1000.0

            try:
                chat_resp = await asyncio.wait_for(
                    self._router_client.chat(
                        messages=messages,
                        task_type=task_type,
                        model=model,
                        correlation_id=correlation_id,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                elapsed = (time.monotonic() - self._started_at) * 1000
                raise ModelCallTimeout(elapsed, self._timeout_ms)
            except asyncio.CancelledError:
                ModelCallContext._total_cancellations += 1
                raise ModelCallCancelled(self._cancel_reason or "task_cancelled")

            elapsed = (time.monotonic() - self._started_at) * 1000

            result = ModelCallResult(
                assistant_text=chat_resp.get("response", "") or chat_resp.get("text", "") or "",
                tool_calls=chat_resp.get("tool_calls") or [],
                elapsed_ms=round(elapsed, 1),
            )

            self._completed = True
            return result

        finally:
            ModelCallContext._active_contexts -= 1
            self._task = None

    def cancel(self, reason: str = "user_cancel") -> bool:
        """
        Cancel the in-flight model call.

        Returns True if a cancellation was triggered, False if no call was active.
        Safe to call multiple times.
        """
        self._cancelled = True
        self._cancel_reason = reason

        if self._task is not None and not self._task.done():
            self._task.cancel()
            logger.info("Model call cancelled: reason=%s", reason)
            return True

        return False

    @classmethod
    def get_active_count(cls) -> int:
        """Number of model calls currently in-flight across all contexts."""
        return cls._active_contexts

    @classmethod
    def get_total_cancellations(cls) -> int:
        """Total number of cancellations since process start."""
        return cls._total_cancellations

    @classmethod
    def reset_counters(cls):
        """Reset class-level counters (for testing)."""
        cls._active_contexts = 0
        cls._total_cancellations = 0


class TurnCancellationManager:
    """
    Manages cancellation tokens for active turns in a stream session.

    Each active turn gets a ModelCallContext. When control.cancel arrives,
    the manager cancels the active turn's context.

    Invariant: at most one active turn per session at any time.
    """

    def __init__(self):
        self._active_turn: Optional[str] = None  # turn_id
        self._active_ctx: Optional[ModelCallContext] = None
        self._cancelled_turns: List[str] = []

    @property
    def active_turn_id(self) -> Optional[str]:
        return self._active_turn

    @property
    def cancelled_turns(self) -> List[str]:
        return list(self._cancelled_turns)

    def begin_turn(self, turn_id: str, ctx: ModelCallContext):
        """Register a new active turn with its model call context."""
        # Cancel any previous turn (active or not yet started)
        if self._active_ctx is not None:
            self._active_ctx.cancel(reason="new_turn_override")
            if self._active_turn:
                self._cancelled_turns.append(self._active_turn)

        self._active_turn = turn_id
        self._active_ctx = ctx

    def cancel_active(self, reason: str = "user_cancel") -> Optional[str]:
        """
        Cancel the currently active turn.

        Returns the cancelled turn_id, or None if no active turn.
        """
        if self._active_ctx is not None:
            cancelled_id = self._active_turn
            self._active_ctx.cancel(reason=reason)
            if cancelled_id:
                self._cancelled_turns.append(cancelled_id)
            self._active_turn = None
            self._active_ctx = None
            return cancelled_id
        return None

    def end_turn(self, turn_id: str):
        """Mark a turn as completed (not cancelled)."""
        if self._active_turn == turn_id:
            self._active_turn = None
            self._active_ctx = None

    def is_turn_cancelled(self, turn_id: str) -> bool:
        """Check if a specific turn was cancelled."""
        return turn_id in self._cancelled_turns

    def get_stats(self) -> Dict[str, Any]:
        """Return cancellation statistics."""
        return {
            "active_turn": self._active_turn,
            "cancelled_count": len(self._cancelled_turns),
            "cancelled_turns": self._cancelled_turns[-10:],  # last 10
        }
