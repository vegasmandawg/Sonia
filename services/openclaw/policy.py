"""
OpenClaw Policy Engine
Enforces allowlists and sandbox constraints for safe execution.
"""

from typing import Any, Dict, List, Set, Optional
from enum import Enum
from pathlib import Path


# ============================================================================
# Security Tiers
# ============================================================================

class SecurityTier(Enum):
    """Tool security tiers."""
    
    TIER_0_READONLY = "TIER_0_READONLY"      # Read operations only
    TIER_1_COMPUTE = "TIER_1_COMPUTE"        # CPU-bound operations
    TIER_2_CREATE = "TIER_2_CREATE"          # File/directory creation
    TIER_3_DESTRUCTIVE = "TIER_3_DESTRUCTIVE"  # Deletion/modification


# ============================================================================
# Allowlist Policies
# ============================================================================

class ShellCommandAllowlist:
    """
    Allowlist for shell commands.
    Only these PowerShell commands are permitted.
    """
    
    ALLOWED_COMMANDS = {
        # File system inspection (read-only)
        "Get-ChildItem",
        "Get-Item",
        "Get-Content",
        "Test-Path",
        "Resolve-Path",
        "Get-Location",
        
        # Process inspection (read-only)
        "Get-Process",
        "Get-Service",
        
        # Version/info queries
        "python",
        "$PSVersionTable",
        "Get-PSVersion",
    }
    
    # Commands that are always blocked regardless of context
    BLOCKED_COMMANDS = {
        "Remove-Item",
        "Delete",
        "Clear-Content",
        "Remove-PSSession",
        "Stop-Process",
        "Stop-Service",
        "Set-ExecutionPolicy",
        "New-PSDrive",
        "New-PSSession",
        "Invoke-Command",
        "Invoke-WebRequest",
        "Invoke-Expression",
        "IEX",
        "&",  # Call operator
        ".",  # Dot-source operator
    }
    
    @classmethod
    def is_allowed(cls, command: str) -> bool:
        """Check if command is in allowlist."""
        # Extract first word (command name)
        parts = command.strip().split()
        if not parts:
            return False
        
        cmd = parts[0]
        
        # Block explicitly forbidden commands first
        if any(blocked in cmd for blocked in cls.BLOCKED_COMMANDS):
            return False
        
        # Check if in allowed list (case-insensitive)
        return any(cmd.lower() == allowed.lower() for allowed in cls.ALLOWED_COMMANDS)


class FilesystemSandbox:
    """
    Filesystem sandbox enforcement.
    All file operations are restricted to S:\ root.
    """
    
    # Root directory for all operations
    SANDBOX_ROOT = Path("S:\\")
    
    # Sensitive paths that are always blocked
    BLOCKED_PATHS = {
        Path("S:\\Windows"),
        Path("S:\\Program Files"),
        Path("S:\\Program Files (x86)"),
        Path("S:\\ProgramData"),
        Path("S:\\System32"),
    }
    
    @classmethod
    def is_path_safe(cls, path: str) -> bool:
        """
        Check if path is safe for access.
        Must be within S:\ and not a blocked path.
        """
        try:
            # Normalize path
            p = Path(path).resolve()
            
            # Must be within sandbox root
            if not str(p).startswith(str(cls.SANDBOX_ROOT)):
                return False
            
            # Cannot be in blocked paths
            for blocked in cls.BLOCKED_PATHS:
                if str(p).startswith(str(blocked)):
                    return False
            
            return True
        except Exception:
            return False
    
    @classmethod
    def get_safe_path(cls, path: str) -> Optional[Path]:
        """
        Return normalized path if safe, None otherwise.
        """
        if cls.is_path_safe(path):
            return Path(path).resolve()
        return None


# ============================================================================
# Policy Enforcement
# ============================================================================

class ExecutionPolicy:
    """
    Enforces security policies on tool execution.
    """
    
    def __init__(self):
        self.denied_log: List[Dict[str, Any]] = []
    
    def check_shell_command(self, command: str) -> tuple[bool, Optional[str]]:
        """
        Check if shell command is allowed.
        Returns (allowed, reason_if_denied)
        """
        if not ShellCommandAllowlist.is_allowed(command):
            reason = f"Command '{command}' not in allowlist"
            self.denied_log.append({
                "policy_type": "shell_command",
                "command": command,
                "reason": reason
            })
            return False, reason
        
        return True, None
    
    def check_file_path(self, path: str, operation: str) -> tuple[bool, Optional[str]]:
        """
        Check if file path is allowed.
        Returns (allowed, reason_if_denied)
        """
        if not FilesystemSandbox.is_path_safe(path):
            reason = f"Path '{path}' is outside sandbox or is protected"
            self.denied_log.append({
                "policy_type": "file_path",
                "path": path,
                "operation": operation,
                "reason": reason
            })
            return False, reason
        
        return True, None
    
    def check_timeout(self, timeout_ms: int, max_timeout_ms: int = 15000) -> tuple[bool, Optional[str]]:
        """
        Check if timeout value is reasonable.
        Returns (allowed, reason_if_denied)
        """
        if timeout_ms > max_timeout_ms:
            reason = f"Timeout {timeout_ms}ms exceeds maximum {max_timeout_ms}ms"
            self.denied_log.append({
                "policy_type": "timeout",
                "timeout_ms": timeout_ms,
                "max_timeout_ms": max_timeout_ms,
                "reason": reason
            })
            return False, reason
        
        return True, None
    
    def clear_denied_log(self):
        """Clear the denial log."""
        self.denied_log.clear()
    
    def get_denied_count(self) -> int:
        """Get count of denied operations."""
        return len(self.denied_log)


# ============================================================================
# Global Policy Instance
# ============================================================================

_global_policy: Optional[ExecutionPolicy] = None


def get_policy() -> ExecutionPolicy:
    """Get or create global execution policy instance."""
    global _global_policy
    if _global_policy is None:
        _global_policy = ExecutionPolicy()
    return _global_policy
