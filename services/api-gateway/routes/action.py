"""
API Gateway - Action Route
Orchestrates tool execution through OpenClaw.
"""

import time
from typing import Optional, Dict, Any
from clients.openclaw_client import OpenclawClient, OpenclawClientError


async def handle_action(
    tool_name: str,
    args: Dict[str, Any],
    openclaw_client: OpenclawClient,
    correlation_id: Optional[str] = None,
    timeout_ms: int = 5000
) -> Dict[str, Any]:
    """
    Handle action request with orchestration to OpenClaw.
    
    Flow:
    1. Validate tool_name and args
    2. Call OpenClaw /execute
    3. Track result status and duration
    4. Return standard envelope with execution result
    
    Args:
        tool_name: Name of tool to execute
        args: Tool arguments
        openclaw_client: OpenClaw client
        correlation_id: Optional correlation ID for tracing
        timeout_ms: Execution timeout in milliseconds
    
    Returns:
        Response dict with standard envelope format
    """
    start_time = time.time()
    
    try:
        # Validate inputs
        if not tool_name:
            total_elapsed = (time.time() - start_time) * 1000
            return {
                "ok": False,
                "service": "api-gateway",
                "operation": "action",
                "correlation_id": correlation_id,
                "duration_ms": total_elapsed,
                "data": None,
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "tool_name is required",
                    "details": {}
                }
            }
        
        if not args:
            args = {}
        
        # Call OpenClaw to execute tool
        openclaw_start = time.time()
        try:
            execute_result = await openclaw_client.execute(
                tool_name=tool_name,
                args=args,
                timeout_ms=timeout_ms,
                correlation_id=correlation_id
            )
            openclaw_elapsed = (time.time() - openclaw_start) * 1000
        
        except OpenclawClientError as e:
            total_elapsed = (time.time() - start_time) * 1000
            return {
                "ok": False,
                "service": "api-gateway",
                "operation": "action",
                "correlation_id": correlation_id,
                "duration_ms": total_elapsed,
                "data": None,
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "details": e.details
                }
            }
        
        # Success response
        total_elapsed = (time.time() - start_time) * 1000
        
        # Check if execution was successful in OpenClaw response
        execution_ok = execute_result.get("status") == "executed"
        
        return {
            "ok": execution_ok,
            "service": "api-gateway",
            "operation": "action",
            "correlation_id": correlation_id,
            "duration_ms": total_elapsed,
            "data": {
                "tool_name": tool_name,
                "status": execute_result.get("status"),
                "result": execute_result.get("result", {}),
                "side_effects": execute_result.get("side_effects", []),
                "openclaw": {
                    "status": "ok",
                    "duration_ms": openclaw_elapsed
                }
            },
            "error": {
                "code": execute_result.get("status") if not execution_ok else None,
                "message": execute_result.get("message") if not execution_ok else None,
                "details": execute_result.get("error") if not execution_ok else None
            } if not execution_ok else None
        }
    
    except Exception as e:
        total_elapsed = (time.time() - start_time) * 1000
        return {
            "ok": False,
            "service": "api-gateway",
            "operation": "action",
            "correlation_id": correlation_id,
            "duration_ms": total_elapsed,
            "data": None,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(e),
                "details": {"error_type": type(e).__name__}
            }
        }
