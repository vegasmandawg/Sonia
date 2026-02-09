"""
OpenClaw Browser Executor
Executes browser operations (open URL).
Phase 1: Implements open operation only.
"""

import time
import webbrowser
from typing import Any, Dict, Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse


class BrowserExecutor:
    """
    Executes browser operations.
    Phase 1: open operation to launch URLs.
    """
    
    DEFAULT_TIMEOUT_MS = 5000
    MAX_TIMEOUT_MS = 15000
    
    # Allowlist of safe URL schemes
    SAFE_SCHEMES = {"http", "https"}
    
    # Block list of domains (never open these)
    BLOCKED_DOMAINS = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "192.168.0.1",
        "10.0.0.1",
    }
    
    def __init__(self):
        self.execution_log: list[Dict[str, Any]] = []
    
    def open(
        self,
        url: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Open URL in default browser.
        
        Args:
            url: URL to open
            timeout_ms: Execution timeout in milliseconds
            correlation_id: Request correlation ID for tracing
        
        Returns:
            (success, result_dict, error_message)
        """
        start_time = time.time()
        
        # Validate timeout
        timeout_ms = timeout_ms or self.DEFAULT_TIMEOUT_MS
        if timeout_ms > self.MAX_TIMEOUT_MS:
            error_msg = f"Timeout {timeout_ms}ms exceeds maximum {self.MAX_TIMEOUT_MS}ms"
            self._log_execution(
                operation="open",
                url=url,
                success=False,
                error="timeout_exceeded",
                elapsed_ms=(time.time() - start_time) * 1000,
                correlation_id=correlation_id
            )
            return False, {}, error_msg
        
        # Validate URL
        allowed, url_err = self._validate_url(url)
        if not allowed:
            self._log_execution(
                operation="open",
                url=url,
                success=False,
                error=url_err,
                elapsed_ms=(time.time() - start_time) * 1000,
                correlation_id=correlation_id
            )
            return False, {}, url_err
        
        try:
            # Open URL
            success = webbrowser.open(url, new=1, autoraise=True)
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Log execution
            self._log_execution(
                operation="open",
                url=url,
                success=success,
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            
            if not success:
                return False, {}, "Failed to open browser"
            
            # Prepare result
            result_dict = {
                "url": url,
                "opened": True,
                "elapsed_ms": elapsed_ms,
                "success": True
            }
            
            return True, result_dict, None
        
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = f"Open failed: {str(e)}"
            self._log_execution(
                operation="open",
                url=url,
                success=False,
                error=str(e),
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            return False, {}, error_msg
    
    def _validate_url(self, url: str) -> Tuple[bool, Optional[str]]:
        """
        Validate URL for safety.
        Returns (valid, error_reason)
        """
        try:
            # Parse URL
            parsed = urlparse(url)
            
            # Check scheme
            if parsed.scheme not in self.SAFE_SCHEMES:
                return False, f"Unsafe URL scheme: {parsed.scheme}"
            
            # Check domain is not localhost or internal
            netloc = parsed.netloc.lower()
            
            # Remove port if present
            hostname = netloc.split(":")[0]
            
            # Check blocked domains
            if hostname in self.BLOCKED_DOMAINS:
                return False, f"Blocked domain: {hostname}"
            
            # Basic URL length check
            if len(url) > 4096:
                return False, "URL too long (max 4096 chars)"
            
            return True, None
        
        except Exception as e:
            return False, f"Invalid URL: {str(e)}"
    
    def _log_execution(
        self,
        operation: str,
        url: str,
        success: bool,
        error: Optional[str] = None,
        elapsed_ms: float = 0.0,
        correlation_id: Optional[str] = None
    ):
        """Log a browser operation."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "operation": operation,
            "url": url,
            "success": success,
            "elapsed_ms": elapsed_ms,
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
