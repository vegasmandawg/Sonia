"""
Tool Execution Engine

Executes tools with risk-based approval workflow and state management.
Implements async execution, timeout handling, and error recovery.
"""

import asyncio
import logging
import time
from typing import Optional, Dict, Any, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from enum import Enum

from tool_registry import (
    RiskTier,
    ToolRegistry,
    ToolDefinition,
    get_registry
)

logger = logging.getLogger(__name__)


class ExecutionStatus(str, Enum):
    """Tool execution status."""
    PENDING = "pending"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass
class ExecutionRequest:
    """Represents a tool execution request."""
    tool_name: str
    parameters: Dict[str, Any]
    request_id: str = None
    user_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    timeout_seconds: Optional[int] = None

    def __post_init__(self):
        """Initialize request ID."""
        if not self.request_id:
            self.request_id = str(uuid4())


@dataclass
class ExecutionResult:
    """Represents tool execution result."""
    request_id: str
    tool_name: str
    status: ExecutionStatus
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Set timestamp."""
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "timestamp": self.timestamp,
            "metadata": self.metadata or {}
        }


class ApprovalPolicy:
    """Defines tool approval policies."""

    def __init__(self):
        """Initialize approval policy."""
        self.logger = logging.getLogger(f"{__name__}.ApprovalPolicy")

    def requires_approval(self, tool_def: ToolDefinition, request: ExecutionRequest) -> bool:
        """
        Determine if execution requires approval.

        Args:
            tool_def: Tool definition
            request: Execution request

        Returns:
            True if approval required
        """
        # Always require approval for TIER_3
        if tool_def.risk_tier == RiskTier.TIER_3:
            return True

        # Require approval if tool marked as such
        if tool_def.requires_approval:
            return True

        # Require approval for destructive operations
        if "destructive" in (tool_def.tags or []):
            return True

        return False

    def can_execute(
        self,
        tool_def: ToolDefinition,
        request: ExecutionRequest,
        user_approved: bool = False
    ) -> tuple:
        """
        Check if execution can proceed.

        Args:
            tool_def: Tool definition
            request: Execution request
            user_approved: Whether user has approved

        Returns:
            (can_execute, reason)
        """
        # Check if tool is deprecated
        if tool_def.deprecated:
            return False, "Tool is deprecated"

        # Check if deprecated tool used via alias
        if request.tool_name != tool_def.name:
            if tool_def.deprecated:
                return False, f"Tool '{tool_def.name}' (alias: {request.tool_name}) is deprecated"

        # Check approval requirement
        if self.requires_approval(tool_def, request) and not user_approved:
            return False, f"Tool '{tool_def.name}' requires approval"

        # Check authentication requirement
        if tool_def.requires_authentication and not request.user_id:
            return False, "Tool requires authentication"

        return True, ""


class RateLimiter:
    """Rate limiting for tool execution."""

    def __init__(self):
        """Initialize rate limiter."""
        self.logger = logging.getLogger(f"{__name__}.RateLimiter")
        self.call_times: Dict[str, list] = {}

    def check_limit(self, tool_name: str, rate_limit: Optional[int], time_window: int = 60) -> bool:
        """
        Check if rate limit exceeded.

        Args:
            tool_name: Tool name
            rate_limit: Max calls per minute (None = no limit)
            time_window: Time window in seconds

        Returns:
            True if within limit
        """
        if rate_limit is None:
            return True

        if tool_name not in self.call_times:
            self.call_times[tool_name] = []

        current_time = time.time()
        cutoff_time = current_time - time_window

        # Remove old calls outside time window
        self.call_times[tool_name] = [
            t for t in self.call_times[tool_name]
            if t > cutoff_time
        ]

        # Check if limit exceeded
        if len(self.call_times[tool_name]) >= rate_limit:
            return False

        return True

    def record_call(self, tool_name: str) -> None:
        """Record tool call for rate limiting."""
        if tool_name not in self.call_times:
            self.call_times[tool_name] = []
        self.call_times[tool_name].append(time.time())


class ToolExecutor:
    """Executes tools with risk-based approval and state management."""

    def __init__(self, registry: Optional[ToolRegistry] = None):
        """
        Initialize tool executor.

        Args:
            registry: Tool registry (uses global if None)
        """
        self.logger = logging.getLogger(f"{__name__}.ToolExecutor")
        self.registry = registry or get_registry()
        self.approval_policy = ApprovalPolicy()
        self.rate_limiter = RateLimiter()
        self.execution_history: Dict[str, ExecutionResult] = {}

    async def execute(
        self,
        request: ExecutionRequest,
        user_approved: bool = False
    ) -> ExecutionResult:
        """
        Execute a tool.

        Args:
            request: Execution request
            user_approved: Whether user has approved execution

        Returns:
            Execution result

        Raises:
            ValueError: If tool not found or parameters invalid
        """
        start_time = time.time()

        try:
            # Get tool definition
            tool_def = self.registry.get_tool(request.tool_name)
            if not tool_def:
                raise ValueError(f"Tool not found: {request.tool_name}")

            # Validate parameters
            valid, error_msg = tool_def.validate_parameters(request.parameters)
            if not valid:
                raise ValueError(f"Parameter validation failed: {error_msg}")

            # Check approval
            can_execute, reason = self.approval_policy.can_execute(
                tool_def,
                request,
                user_approved
            )
            if not can_execute:
                self.logger.warning(
                    f"Execution blocked for {request.tool_name}: {reason}"
                )
                return ExecutionResult(
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    status=ExecutionStatus.REQUIRES_APPROVAL,
                    error=reason,
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # Check rate limit
            if not self.rate_limiter.check_limit(tool_def.name, tool_def.rate_limit):
                error = f"Rate limit exceeded for {tool_def.name}"
                self.logger.warning(error)
                return ExecutionResult(
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    status=ExecutionStatus.FAILED,
                    error=error,
                    execution_time_ms=(time.time() - start_time) * 1000
                )

            # Get implementation
            implementation = self.registry.get_implementation(request.tool_name)
            if not implementation:
                raise ValueError(f"No implementation for tool: {request.tool_name}")

            # Record rate limit
            self.rate_limiter.record_call(tool_def.name)

            # Execute with timeout
            timeout = request.timeout_seconds or tool_def.timeout_seconds
            try:
                if asyncio.iscoroutinefunction(implementation):
                    result = await asyncio.wait_for(
                        implementation(**request.parameters),
                        timeout=timeout
                    )
                else:
                    # Run sync function in thread pool
                    result = await asyncio.wait_for(
                        asyncio.to_thread(
                            implementation,
                            **request.parameters
                        ),
                        timeout=timeout
                    )

                execution_time_ms = (time.time() - start_time) * 1000

                # Record execution
                self.registry.record_execution(
                    tool_def.name,
                    success=True,
                    execution_time_ms=execution_time_ms
                )

                execution_result = ExecutionResult(
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    status=ExecutionStatus.COMPLETED,
                    result=result,
                    execution_time_ms=execution_time_ms,
                    metadata={
                        "risk_tier": tool_def.risk_tier.value,
                        "category": tool_def.category.value
                    }
                )

                # Store in history
                self.execution_history[request.request_id] = execution_result

                return execution_result

            except asyncio.TimeoutError:
                execution_time_ms = (time.time() - start_time) * 1000

                self.registry.record_execution(
                    tool_def.name,
                    success=False,
                    execution_time_ms=execution_time_ms,
                    error=f"Timeout after {timeout}s"
                )

                return ExecutionResult(
                    request_id=request.request_id,
                    tool_name=request.tool_name,
                    status=ExecutionStatus.TIMEOUT,
                    error=f"Tool execution exceeded timeout of {timeout}s",
                    execution_time_ms=execution_time_ms
                )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_msg = str(e)

            # Try to record execution
            try:
                tool_def = self.registry.get_tool(request.tool_name)
                if tool_def:
                    self.registry.record_execution(
                        tool_def.name,
                        success=False,
                        execution_time_ms=execution_time_ms,
                        error=error_msg
                    )
            except Exception:
                pass

            self.logger.error(
                f"Tool execution failed for {request.tool_name}: {error_msg}",
                exc_info=True
            )

            return ExecutionResult(
                request_id=request.request_id,
                tool_name=request.tool_name,
                status=ExecutionStatus.FAILED,
                error=error_msg,
                execution_time_ms=execution_time_ms
            )

    async def batch_execute(
        self,
        requests: list,
        user_approved: bool = False,
        parallel: bool = False
    ) -> list:
        """
        Execute multiple tools.

        Args:
            requests: List of ExecutionRequest objects
            user_approved: Whether user has approved all executions
            parallel: Whether to execute in parallel

        Returns:
            List of ExecutionResult objects
        """
        if parallel:
            # Execute concurrently
            results = await asyncio.gather(
                *[self.execute(req, user_approved) for req in requests]
            )
        else:
            # Execute sequentially
            results = []
            for request in requests:
                result = await self.execute(request, user_approved)
                results.append(result)

        return results

    def get_execution_history(
        self,
        tool_name: Optional[str] = None,
        limit: int = 100
    ) -> list:
        """
        Get execution history.

        Args:
            tool_name: Filter by tool name
            limit: Max results

        Returns:
            List of ExecutionResult objects
        """
        results = list(self.execution_history.values())

        if tool_name:
            results = [r for r in results if r.tool_name == tool_name]

        # Return most recent first
        results = sorted(
            results,
            key=lambda r: r.timestamp,
            reverse=True
        )

        return results[:limit]

    def clear_history(self) -> int:
        """
        Clear execution history.

        Returns:
            Number of entries cleared
        """
        count = len(self.execution_history)
        self.execution_history.clear()
        return count
