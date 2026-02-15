"""
OpenClaw Tool Registry
Deterministic executor registry and dispatcher.
"""

from typing import Any, Dict, Optional, Callable
from datetime import datetime
from pathlib import Path
import os
import uuid
import sys

OPENCLAW_DIR = Path(__file__).resolve().parent
SERVICES_DIR = OPENCLAW_DIR.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

# Root contract — all file I/O must stay within this boundary
_ROOT_CONTRACT = r"S:\\"

# Backward-compatible aliases (catalog/API -> canonical runtime name)
_TOOL_ALIASES: Dict[str, str] = {
    "filesystem.read_file": "file.read",
    "filesystem.write_file": "file.write",
    "shell.run_command": "shell.run",
    "shell.run_powershell_script": "shell.run",
}


def _validate_path(path: str) -> Optional[str]:
    """Validate path is within the root contract. Returns error string or None."""
    try:
        resolved = Path(path).resolve()
        root = Path(_ROOT_CONTRACT).resolve()
        if not str(resolved).startswith(str(root)):
            return f"path escapes root contract: {path}"
    except (OSError, ValueError) as e:
        return f"invalid path: {e}"
    return None

from openclaw.schemas import ExecuteResponse, ExecuteRequest, ToolMetadata, RegistryStats
from openclaw.policy import get_policy, SecurityTier
from openclaw.executors.shell_exec import ShellExecutor
from openclaw.executors.file_exec import FileExecutor
from openclaw.executors.browser_exec import BrowserExecutor
from openclaw.executors.desktop_exec import DesktopExecutor
from openclaw.executors.web_exec import WebExecutor
from openclaw.executors.notification_exec import NotificationExecutor


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

        path_err = _validate_path(path)
        if path_err:
            return {"success": False, "result": None, "error": path_err}

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

        path_err = _validate_path(path)
        if path_err:
            return {"success": False, "result": None, "error": path_err}

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
# Desktop Executor Implementations (Stage 5 M3)
# ============================================================================

class AppLaunchExecutor(ToolExecutor):
    """Executor for app.launch tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        target = args.get("target", "")
        app_args = args.get("args", [])
        if not target:
            return {"error": "target argument required"}
        success, result, error = self.desktop.app_launch(target, app_args, **kwargs)
        return {"success": success, "result": result, "error": error}


class AppCloseExecutor(ToolExecutor):
    """Executor for app.close tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        target = args.get("target", "")
        force = args.get("force", False)
        if not target:
            return {"error": "target argument required"}
        success, result, error = self.desktop.app_close(target, force, **kwargs)
        return {"success": success, "result": result, "error": error}


class WindowFocusExecutor(ToolExecutor):
    """Executor for window.focus tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        title = args.get("title", "")
        if not title:
            return {"error": "title argument required"}
        success, result, error = self.desktop.window_focus(title, **kwargs)
        return {"success": success, "result": result, "error": error}


class WindowListExecutor(ToolExecutor):
    """Executor for window.list tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        success, result, error = self.desktop.window_list(**kwargs)
        return {"success": success, "result": result, "error": error}


class KeyboardTypeExecutor(ToolExecutor):
    """Executor for keyboard.type tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        text = args.get("text", "")
        if not text:
            return {"error": "text argument required"}
        success, result, error = self.desktop.keyboard_type(text, **kwargs)
        return {"success": success, "result": result, "error": error}


class KeyboardHotkeyExecutor(ToolExecutor):
    """Executor for keyboard.hotkey tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        keys = args.get("keys", "")
        if not keys:
            return {"error": "keys argument required"}
        success, result, error = self.desktop.keyboard_hotkey(keys, **kwargs)
        return {"success": success, "result": result, "error": error}


class MouseClickExecutor(ToolExecutor):
    """Executor for mouse.click tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        x = args.get("x")
        y = args.get("y")
        button = args.get("button", "left")
        if x is None or y is None:
            return {"error": "x and y arguments required"}
        success, result, error = self.desktop.mouse_click(x, y, button, **kwargs)
        return {"success": success, "result": result, "error": error}


class ClipboardReadExecutor(ToolExecutor):
    """Executor for clipboard.read tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        success, result, error = self.desktop.clipboard_read(**kwargs)
        return {"success": success, "result": result, "error": error}


class ClipboardWriteExecutor(ToolExecutor):
    """Executor for clipboard.write tool."""
    def __init__(self):
        self.desktop = DesktopExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        text = args.get("text", "")
        if text is None:
            return {"error": "text argument required"}
        success, result, error = self.desktop.clipboard_write(text, **kwargs)
        return {"success": success, "result": result, "error": error}


# ============================================================================
# Web Executor Implementations (Phase 5b)
# ============================================================================

class WebSearchExecutor(ToolExecutor):
    """Executor for web.search tool."""
    def __init__(self):
        self.web = WebExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        query = args.get("query", "")
        max_results = args.get("max_results", 5)
        if not query:
            return {"error": "query argument required"}
        success, result, error = self.web.search(
            query, max_results=max_results, **kwargs)
        return {"success": success, "result": result, "error": error}


class WebFetchExecutor(ToolExecutor):
    """Executor for web.fetch tool."""
    def __init__(self):
        self.web = WebExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        url = args.get("url", "")
        max_chars = args.get("max_chars", 5000)
        if not url:
            return {"error": "url argument required"}
        success, result, error = self.web.fetch(
            url, max_chars=max_chars, **kwargs)
        return {"success": success, "result": result, "error": error}


class NotificationSendExecutor(ToolExecutor):
    """Executor for notification.send tool."""
    def __init__(self):
        self.notifier = NotificationExecutor()
    def execute(self, tool_name: str, args: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        title = args.get("title", "")
        body = args.get("body", "")
        if not title:
            return {"error": "title argument required"}
        success, result, error = self.notifier.send(
            title, body=body, **kwargs)
        return {"success": success, "result": result, "error": error}


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

        # ── Stage 5 M3: Desktop tools ────────────────────────────

        # Tool 5: app.launch
        self.register_tool(
            name="app.launch",
            display_name="App Launch",
            description="Launch an application by name or path",
            tier=SecurityTier.TIER_1_COMPUTE.value,
            requires_sandboxing=False,
            default_timeout_ms=10000,
            executor=AppLaunchExecutor()
        )

        # Tool 6: app.close
        self.register_tool(
            name="app.close",
            display_name="App Close",
            description="Close an application by name",
            tier=SecurityTier.TIER_2_CREATE.value,
            requires_sandboxing=False,
            default_timeout_ms=10000,
            executor=AppCloseExecutor()
        )

        # Tool 7: window.focus
        self.register_tool(
            name="window.focus",
            display_name="Window Focus",
            description="Focus a window by title",
            tier=SecurityTier.TIER_1_COMPUTE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=WindowFocusExecutor()
        )

        # Tool 8: window.list
        self.register_tool(
            name="window.list",
            display_name="Window List",
            description="List all visible windows",
            tier=SecurityTier.TIER_0_READONLY.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=WindowListExecutor()
        )

        # Tool 9: keyboard.type
        self.register_tool(
            name="keyboard.type",
            display_name="Keyboard Type",
            description="Type text using SendKeys",
            tier=SecurityTier.TIER_2_CREATE.value,
            requires_sandboxing=False,
            default_timeout_ms=10000,
            executor=KeyboardTypeExecutor()
        )

        # Tool 10: keyboard.hotkey
        self.register_tool(
            name="keyboard.hotkey",
            display_name="Keyboard Hotkey",
            description="Send a keyboard hotkey combination",
            tier=SecurityTier.TIER_2_CREATE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=KeyboardHotkeyExecutor()
        )

        # Tool 11: mouse.click
        self.register_tool(
            name="mouse.click",
            display_name="Mouse Click",
            description="Click at screen coordinates",
            tier=SecurityTier.TIER_2_CREATE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=MouseClickExecutor()
        )

        # Tool 12: clipboard.read
        self.register_tool(
            name="clipboard.read",
            display_name="Clipboard Read",
            description="Read text from the Windows clipboard",
            tier=SecurityTier.TIER_0_READONLY.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=ClipboardReadExecutor()
        )

        # Tool 13: clipboard.write
        self.register_tool(
            name="clipboard.write",
            display_name="Clipboard Write",
            description="Write text to the Windows clipboard",
            tier=SecurityTier.TIER_2_CREATE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=ClipboardWriteExecutor()
        )

        # ── Phase 5b: Web + Notification tools ────────────────────

        # Tool 14: web.search
        self.register_tool(
            name="web.search",
            display_name="Web Search",
            description="Search the web using DuckDuckGo (no API key needed)",
            tier=SecurityTier.TIER_0_READONLY.value,
            requires_sandboxing=False,
            default_timeout_ms=15000,
            executor=WebSearchExecutor()
        )

        # Tool 15: web.fetch
        self.register_tool(
            name="web.fetch",
            display_name="Web Fetch",
            description="Fetch and extract text content from a URL",
            tier=SecurityTier.TIER_0_READONLY.value,
            requires_sandboxing=False,
            default_timeout_ms=15000,
            executor=WebFetchExecutor()
        )

        # Tool 16: notification.send
        self.register_tool(
            name="notification.send",
            display_name="Notification Send",
            description="Send a Windows toast notification",
            tier=SecurityTier.TIER_1_COMPUTE.value,
            requires_sandboxing=False,
            default_timeout_ms=5000,
            executor=NotificationSendExecutor()
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
        requested_tool = request.tool_name
        tool_name = _TOOL_ALIASES.get(requested_tool, requested_tool)
        args = dict(request.args)

        # Alias argument normalization
        if requested_tool == "shell.run_powershell_script" and "script" in args and "command" not in args:
            args["command"] = args["script"]
        
        # Check if tool is registered
        if tool_name not in self.tools:
            response = ExecuteResponse(
                status="not_implemented",
                tool_name=tool_name,
                message="Tool not yet implemented",
                correlation_id=correlation_id
            )
            self._log_execution(tool_name, "not_implemented", correlation_id)
            return response
        
        # Get executor
        executor = self.executors[tool_name]
        
        # Execute tool
        try:
            result = executor.execute(
                tool_name,
                args,
                timeout_ms=request.timeout_ms,
                correlation_id=correlation_id
            )
            if requested_tool != tool_name:
                result["_alias"] = {
                    "requested_tool": requested_tool,
                    "canonical_tool": tool_name,
                }
            
            # Check for errors
            if result.get("error"):
                response = ExecuteResponse(
                    status="error",
                    tool_name=tool_name,
                    error=result["error"],
                    message=f"Execution failed: {result['error']}",
                    correlation_id=correlation_id
                )
                self._log_execution(tool_name, "error", correlation_id, result["error"])
                return response
            
            # Success
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = ExecuteResponse(
                status="executed",
                tool_name=tool_name,
                result=result.get("result", {}),
                side_effects=result.get("side_effects", []),
                correlation_id=correlation_id,
                duration_ms=elapsed
            )
            self._log_execution(tool_name, "executed", correlation_id)
            return response
        
        except Exception as e:
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            response = ExecuteResponse(
                status="error",
                tool_name=tool_name,
                error=str(e),
                message=f"Execution failed: {str(e)}",
                correlation_id=correlation_id,
                duration_ms=elapsed
            )
            self._log_execution(tool_name, "error", correlation_id, str(e))
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
