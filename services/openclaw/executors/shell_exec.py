"""
OpenClaw Shell Executor
Executes shell commands with strict allowlist enforcement and timeout handling.
"""

import subprocess
import time
from typing import Any, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import sys

from policy import get_policy, ShellCommandAllowlist


class ShellExecutor:
    """
    Executes PowerShell commands with strict safety enforcement.
    Only allows commands in the allowlist.
    """
    
    DEFAULT_TIMEOUT_MS = 5000
    MAX_TIMEOUT_MS = 15000
    
    def __init__(self):
        self.policy = get_policy()
        self.execution_log: list[Dict[str, Any]] = []
    
    def execute(
        self,
        command: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Execute a shell command.
        
        Args:
            command: PowerShell command to execute
            timeout_ms: Execution timeout in milliseconds
            correlation_id: Request correlation ID for tracing
        
        Returns:
            (success, result_dict, error_message)
        """
        start_time = time.time()
        
        # Validate timeout
        timeout_ms = timeout_ms or self.DEFAULT_TIMEOUT_MS
        allowed, timeout_err = self.policy.check_timeout(timeout_ms, self.MAX_TIMEOUT_MS)
        if not allowed:
            return False, {}, timeout_err
        
        # Validate command
        allowed, cmd_err = self.policy.check_shell_command(command)
        if not allowed:
            return False, {}, cmd_err
        
        try:
            # Convert timeout from milliseconds to seconds
            timeout_sec = timeout_ms / 1000.0
            
            # Execute command
            result = subprocess.run(
                ["powershell", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False
            )
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Log execution
            self._log_execution(
                command=command,
                success=True,
                stdout_len=len(result.stdout),
                stderr_len=len(result.stderr),
                return_code=result.returncode,
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            
            # Prepare result
            result_dict = {
                "command": command,
                "return_code": result.returncode,
                "stdout": result.stdout[:10000],  # Limit output to 10KB
                "stderr": result.stderr[:10000],
                "elapsed_ms": elapsed_ms,
                "success": result.returncode == 0
            }
            
            return True, result_dict, None
        
        except subprocess.TimeoutExpired:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = f"Command timed out after {timeout_ms}ms"
            self._log_execution(
                command=command,
                success=False,
                error="timeout",
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            return False, {}, error_msg
        
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = f"Execution failed: {str(e)}"
            self._log_execution(
                command=command,
                success=False,
                error=str(e),
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            return False, {}, error_msg
    
    def _log_execution(
        self,
        command: str,
        success: bool,
        stdout_len: Optional[int] = None,
        stderr_len: Optional[int] = None,
        return_code: Optional[int] = None,
        error: Optional[str] = None,
        elapsed_ms: float = 0.0,
        correlation_id: Optional[str] = None
    ):
        """Log a command execution."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "command": command,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "correlation_id": correlation_id
        }
        
        if return_code is not None:
            log_entry["return_code"] = return_code
        if stdout_len is not None:
            log_entry["stdout_bytes"] = stdout_len
        if stderr_len is not None:
            log_entry["stderr_bytes"] = stderr_len
        if error:
            log_entry["error"] = error
        
        self.execution_log.append(log_entry)
    
    def get_execution_log(self) -> list[Dict[str, Any]]:
        """Get execution log."""
        return self.execution_log.copy()
    
    def clear_execution_log(self):
        """Clear execution log."""
        self.execution_log.clear()
