"""
Action Turn Bridge -- v2.7-m4

Bridges the turn pipeline's tool-call execution to the full
Stage 5 action pipeline (plan -> validate -> execute -> verify).

Before v2.7, tool calls in routes/turn.py and routes/stream.py
called openclaw_client.execute() directly. This bridge routes
those calls through ActionPipeline.run(), adding:
  - Capability validation
  - Risk classification
  - Circuit breaker protection
  - Dead letter queue on exhaustion
  - Audit trail per tool call
  - Idempotency key support

Usage in turn handler:
    bridge = ActionTurnBridge(action_pipeline)
    result = await bridge.execute_tool_call(
        tool_name="file.read",
        tool_args={"path": "/tmp/x"},
        session_id="sess-1",
        correlation_id="req_abc",
    )
    if result.executed:
        output = result.output
    elif result.pending_approval:
        action_id = result.action_id  # UI can approve later
    else:
        error = result.error

Usage in stream handler:
    Same API, but stream can also pass through the safety
    classification for backward compat with tool_policy.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("gateway.action_turn_bridge")


# ── Bridge result ────────────────────────────────────────────────────────────

@dataclass
class ToolExecutionResult:
    """
    Normalized result of routing a tool call through the action pipeline.
    Consumed by both turn.py and stream.py handlers.
    """
    tool_name: str = ""
    executed: bool = False
    pending_approval: bool = False
    rejected: bool = False
    output: Dict[str, Any] = field(default_factory=dict)
    side_effects: List[str] = field(default_factory=list)
    action_id: str = ""
    action_state: str = ""
    risk_level: str = "medium"
    error: str = ""
    error_code: str = ""
    duration_ms: float = 0.0
    retries_used: int = 0
    dry_run: bool = False


# ── Bridge ───────────────────────────────────────────────────────────────────

class ActionTurnBridge:
    """
    Wraps ActionPipeline to provide a simple execute_tool_call() interface
    that the turn pipeline and stream handler can use as a drop-in
    replacement for openclaw_client.execute().
    """

    def __init__(self, action_pipeline):
        """
        Args:
            action_pipeline: An ActionPipeline instance (from action_pipeline.py).
        """
        self.pipeline = action_pipeline

    async def execute_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        session_id: str = "",
        correlation_id: str = "",
        timeout_ms: int = 10000,
        max_retries: int = 0,
        dry_run: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> ToolExecutionResult:
        """
        Route a single tool call through the full action pipeline.

        Returns a ToolExecutionResult that cleanly maps to the existing
        ToolCallRecord pattern in turn.py / stream.py.
        """
        from schemas.action import ActionPlanRequest

        t0 = time.time()

        req = ActionPlanRequest(
            intent=tool_name,
            params=tool_args,
            session_id=session_id or None,
            timeout_ms=timeout_ms,
            max_retries=max_retries,
            dry_run=dry_run,
            idempotency_key=idempotency_key,
        )

        try:
            resp = await self.pipeline.run(req, correlation_id=correlation_id)
        except Exception as e:
            elapsed = round((time.time() - t0) * 1000, 2)
            logger.error(
                "Bridge error tool=%s corr=%s: %s",
                tool_name, correlation_id, e,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                error=f"Bridge error: {e}",
                error_code="BRIDGE_ERROR",
                duration_ms=elapsed,
            )

        elapsed = round((time.time() - t0) * 1000, 2)

        # Map ActionPlanResponse to ToolExecutionResult
        result = ToolExecutionResult(
            tool_name=tool_name,
            action_id=resp.action_id,
            action_state=resp.state,
            risk_level=resp.risk_level,
            duration_ms=elapsed,
            dry_run=dry_run,
        )

        if resp.state == "pending_approval":
            result.pending_approval = True
            logger.info(
                "Tool %s pending approval action=%s session=%s",
                tool_name, resp.action_id, session_id,
            )
            return result

        if resp.state == "succeeded":
            result.executed = True
            if resp.execution:
                result.output = resp.execution.output
                result.side_effects = resp.execution.side_effects
                result.retries_used = resp.execution.retries_used
                result.duration_ms = resp.execution.duration_ms
            return result

        if resp.state == "validated" and dry_run:
            result.executed = False
            result.dry_run = True
            return result

        # All other states are failures
        result.rejected = True
        if resp.error:
            result.error = resp.error.get("message", "")
            result.error_code = resp.error.get("code", "")
        if resp.execution:
            result.retries_used = resp.execution.retries_used
            result.duration_ms = resp.execution.duration_ms
        return result

    async def execute_batch(
        self,
        tool_calls: List[Dict[str, Any]],
        session_id: str = "",
        correlation_id: str = "",
        timeout_ms: int = 10000,
        max_retries: int = 0,
    ) -> List[ToolExecutionResult]:
        """
        Execute a list of tool calls sequentially through the pipeline.
        Each call is independent (no short-circuit on failure).
        """
        results = []
        for tc in tool_calls:
            name = tc.get("tool_name", tc.get("name", ""))
            args = tc.get("args", tc.get("arguments", {}))
            r = await self.execute_tool_call(
                tool_name=name,
                tool_args=args,
                session_id=session_id,
                correlation_id=correlation_id,
                timeout_ms=timeout_ms,
                max_retries=max_retries,
            )
            results.append(r)
        return results

    async def approve_pending(self, action_id: str) -> ToolExecutionResult:
        """
        Approve a pending action and execute it.
        Used by the confirmation flow when operator approves.
        """
        try:
            resp = await self.pipeline.approve(action_id)
        except Exception as e:
            return ToolExecutionResult(
                action_id=action_id,
                error=f"Approval error: {e}",
                error_code="APPROVAL_ERROR",
            )

        result = ToolExecutionResult(
            tool_name=resp.intent,
            action_id=resp.action_id,
            action_state=resp.state,
            risk_level=resp.risk_level,
        )

        if resp.state == "succeeded":
            result.executed = True
            if resp.execution:
                result.output = resp.execution.output
                result.side_effects = resp.execution.side_effects
                result.retries_used = resp.execution.retries_used
                result.duration_ms = resp.execution.duration_ms
        else:
            result.rejected = True
            if resp.error:
                result.error = resp.error.get("message", "")
                result.error_code = resp.error.get("code", "")

        return result

    async def deny_pending(self, action_id: str) -> ToolExecutionResult:
        """Deny a pending action."""
        try:
            resp = await self.pipeline.deny(action_id)
        except Exception as e:
            return ToolExecutionResult(
                action_id=action_id,
                error=f"Denial error: {e}",
                error_code="DENIAL_ERROR",
            )

        return ToolExecutionResult(
            tool_name=resp.intent,
            action_id=resp.action_id,
            action_state=resp.state,
            rejected=True,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Expose pipeline store stats."""
        return {
            "pipeline_available": self.pipeline is not None,
        }
