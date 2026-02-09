"""
OpenClaw Tool Registry
Deterministic executor registry and dispatcher.
"""

from typing import Any, Dict, Optional, Callable
from datetime import datetime
import uuid

from schemas import ExecuteResponse, ExecuteRequest, ToolMetadata, RegistryStats
from policy import get_policy, SecurityTier
from executors.shell_exec import ShellExecutor
from executors.file_exec import FileExecutor
from executors.browser_exec import BrowserExecutor


# ============================================================================
# Tool Executor Interface
# ============================================================================

class ToolExecutor:
    """Base class for tool executors."""
    
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Execute tool and return result."""
        raise NotImplementedError


# ============================================================================
# Tool Executor Implementations
# ============================================================================

class ShellRunExecutor(ToolExecutor):
    """Executor for shell.run tool."""
    
    def __init__(self):
        self.shell = ShellExecutor()
    
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Execute shell command."""
        command = args.get("command", "")
        timeout_ms = kwargs.get("timeout_ms")
        correlation_id = kwargs.get("correlation_id")
        
        if not command:
            return {"error": "command argument required"}
        
        success, result, error = self.shell.execute(
            command,
            timeout_ms=timeout_ms,
            correlation_id=correlation_id
        )
        
        return {
            "success": success,
            "result": result,
            "error": error
        }


class FileReadExecutor(ToolExecutor):
    """Executor for file.read tool."""
    
    def __init__(self):
        self.file = FileExecutor()
    
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Read file."""
        path = args.get("path", "")
        timeout_ms = kwargs.get("timeout_ms")
        correlation_id = kwargs.get("correlation_id")
        
        if not path:
            return {"error": "path argument required"}
        
        success, result, error = self.file.read(
            path,
            timeout_ms=timeout_ms,
            correlation_id=correlation_id
        )
        
        return {
            "success": success,
            "result": result,
            "error": error
        }


class FileWriteExecutor(ToolExecutor):
    """Executor for file.write tool."""
    
    def __init__(self):
        self.file = FileExecutor()
    
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Write file."""
        path = args.get("path", "")
        content = args.get("content", "")
        timeout_ms = kwargs.get("timeout_ms")
        correlation_id = kwargs.get("correlation_id")
        
        if not path:
            return {"error": "path argument required"}
        
        if content is None:
            return {"error": "content argument required"}
        
        success, result, error = self.file.write(
            path,
            content,
            timeout_ms=timeout_ms,
            correlation_id=correlation_id
        )
        
        return {
            "success": success,
            "result": result,
            "error": error
        }


class BrowserOpenExecutor(ToolExecutor):
    """Executor for browser.open tool."""
    
    def __init__(self):
        self.browser = BrowserExecutor()
    
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Open URL in browser."""
        url = args.get("url", "")
        timeout_ms = kwargs.get("timeout_ms")
        correlation_id = kwargs.get("correlation_id")
        
        if not url:
            return {"error": "url argument required"}
        
        success, result, error = self.browser.open(
            url,
            timeout_ms=timeout_ms,
            correlation_id=correlation_id
        )
        
        return {
            "success": success,
            "result": result,
            "error": error
        }


# ============================================================================
# Tool Registry
# ============================================================================

class ToolRegistry:
    """
    Deterministic tool registry and dispatcher.
    """
    
    def __init__(self):
        self.tools: Dict[str, ToolMetadata] = {}
        self.executors: Dict[str, ToolExecutor] = {}
        self.execution_log: list[Dict[str, Any]] = []
        self.policy = get_policy()
        
        # Register tools in deterministic order
        self._register_tools()
    
    def _register_tools(self):
        """Register all available tools."""
        
        # Tool 1: shell.run
        self.register_tool(
            name="shell.run",
            display_name="Shell Run",
            description="Execute PowerShell commands with allowlist enforcement",
            tier=SecurityTier.TIER_1_COMPUTE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=ShellRunExecutor()
        )
        
        # Tool 2: file.read
        self.register_tool(
            name="file.read",
            display_name="File Read",
            description="Read file contents from S:\\ sandbox",
            tier=SecurityTier.TIER_0_READONLY.value,
            requires_sandboxing=True,
            default_timeout_ms=5000,
            executor=FileReadExecutor()
        )
        
        # Tool 3: file.write
        self.register_tool(
            name="file.write",
            display_name="File Write",
            description="Write file contents to S:\\ sandbox",
            tier=SecurityTier.TIER_2_CREATE.value,
            requires_sandboxing=True,
            default_timeout_ms=5000,
            executor=FileWriteExecutor()
        )
        
        # Tool 4: browser.open
        self.register_tool(
            name="browser.open",
            display_name="Browser Open",
            description="Open URL in default browser",
            tier=SecurityTier.TIER_1_COMPUTE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=BrowserOpenExecutor()
        )
    
    def register_tool(
        self,
        name: str,
        display_name: str,
        description: str,
        tier: str,
        requires_sandboxing: bool,
        default_timeout_ms: int,
        executor: ToolExecutor
    ):
        """Register a tool."""
        metadata = ToolMetadata(
            name=name,
            display_name=display_name,
            description=description,
            tier=tier,
            requires_sandboxing=requires_sandboxing,
            default_timeout_ms=default_timeout_ms
        )
        
        self.tools[name] = metadata
        self.executors[name] = executor
    
    def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        """
        Execute a tool request.
        Deterministic dispatch to executor.
        """
        start_time = datetime.utcnow()
        correlation_id = request.correlation_id or f"req_{uuid.uuid4().hex[:12]}"
        
        # Check if tool is registered
        if request.tool_name not in self.tools:
            response = ExecuteResponse(
                status="not_implemented",
                tool_name=request.tool_name,
                message="Tool not yet implemented",
                correlation_id=correlation_id
            )
            self._log_execution(request.tool_name, "not_implemented", correlation_id)
            return response
        
        # Get executor
        executor = self.executors[request.tool_name]
        
        # Execute tool
        try:
            result = executor.execute(
                request.tool_name,
                request.args,
                timeout_ms=request.timeout_ms,
                correlation_id=correlation_id
            )
            
            # Check for errors
            if result.get("error"):
                response = ExecuteResponse(
                    status="error",
                    tool_name=request.tool_name,
                    error=result["error"],
                    message=f"Execution failed: {result['error']}",
                    correlation_id=correlation_id
                )
                self._log_execution(request.tool_name, "error", correlation_id, result["error"])
                return response
            
            # Success
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = ExecuteResponse(
                status="executed",
                tool_name=request.tool_name,
                result=result.get("result", {}),
                side_effects=result.get("side_effects", []),
                correlation_id=correlation_id,
                duration_ms=elapsed
            )
            self._log_execution(request.tool_name, "executed", correlation_id)
            return response
        
        except Exception as e:
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = ExecuteResponse(
                status="error",
                tool_name=request.tool_name,
                error=str(e),
                message=f"Execution failed: {str(e)}",
                correlation_id=correlation_id,
                duration_ms=elapsed
            )
            self._log_execution(request.tool_name, "error", correlation_id, str(e))
            return response
    
    def get_tools(self) -> Dict[str, ToolMetadata]:
        """Get all registered tools."""
        return self.tools.copy()
    
    def get_tool(self, tool_name: str) -> Optional[ToolMetadata]:
        """Get specific tool metadata."""
        return self.tools.get(tool_name)
    
    def get_stats(self) -> RegistryStats:
        """Get registry statistics."""
        tools = self.tools.values()
        return RegistryStats(
            total_tools=len(self.tools),
            implemented_tools=len(self.tools),
            readonly_tools=sum(1 for t in tools if "TIER_0" in t.tier),
            compute_tools=sum(1 for t in tools if "TIER_1" in t.tier),
            create_tools=sum(1 for t in tools if "TIER_2" in t.tier),
            destructive_tools=sum(1 for t in tools if "TIER_3" in t.tier)
        )
    
    def _log_execution(
        self,
        tool_name: str,
        status: str,
        correlation_id: str,
        error: Optional[str] = None
    ):
        """Log tool execution."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "tool_name": tool_name,
            "status": status,
            "correlation_id": correlation_id
        }
        
        if error:
            log_entry["error"] = error
        
        self.execution_log.append(log_entry)
    
    def get_execution_log(self) -> list[Dict[str, Any]]:
        """Get execution log."""
        return self.execution_log.copy()
    
    def clear_execution_log(self):
        """Clear execution log."""
        self.execution_log.clear()


# ============================================================================
# Global Registry Instance
# ============================================================================

_global_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Get or create global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry
