"""
OpenClaw File Executor
Executes file operations with strict sandbox enforcement.
Supports: read, write operations only (no deletion).
"""

import time
from typing import Any, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path

from policy import get_policy, FilesystemSandbox


class FileExecutor:
    """
    Executes file operations with strict sandbox enforcement.
    Operations are limited to S:\ root directory.
    """
    
    DEFAULT_TIMEOUT_MS = 5000
    MAX_TIMEOUT_MS = 15000
    MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB max read size
    
    def __init__(self):
        self.policy = get_policy()
        self.execution_log: list[Dict[str, Any]] = []
    
    def read(
        self,
        path: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Read file contents.
        
        Args:
            path: File path to read
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
        
        # Validate path
        allowed, path_err = self.policy.check_file_path(path, "read")
        if not allowed:
            return False, {}, path_err
        
        try:
            file_path = Path(path).resolve()
            
            # Check file exists
            if not file_path.exists():
                error_msg = f"File not found: {path}"
                self._log_execution(
                    operation="read",
                    path=path,
                    success=False,
                    error="not_found",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    correlation_id=correlation_id
                )
                return False, {}, error_msg
            
            # Check it's a file, not directory
            if not file_path.is_file():
                error_msg = f"Not a file: {path}"
                self._log_execution(
                    operation="read",
                    path=path,
                    success=False,
                    error="not_a_file",
                    elapsed_ms=(time.time() - start_time) * 1000,
                    correlation_id=correlation_id
                )
                return False, {}, error_msg
            
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > self.MAX_FILE_SIZE_BYTES:
                error_msg = f"File too large: {file_size} bytes (max {self.MAX_FILE_SIZE_BYTES})"
                self._log_execution(
                    operation="read",
                    path=path,
                    success=False,
                    error="file_too_large",
                    file_size=file_size,
                    elapsed_ms=(time.time() - start_time) * 1000,
                    correlation_id=correlation_id
                )
                return False, {}, error_msg
            
            # Read file
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Log execution
            self._log_execution(
                operation="read",
                path=path,
                success=True,
                file_size=file_size,
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            
            # Prepare result
            result_dict = {
                "path": str(file_path),
                "size_bytes": file_size,
                "content": content,
                "elapsed_ms": elapsed_ms,
                "success": True
            }
            
            return True, result_dict, None
        
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = f"Read failed: {str(e)}"
            self._log_execution(
                operation="read",
                path=path,
                success=False,
                error=str(e),
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            return False, {}, error_msg
    
    def write(
        self,
        path: str,
        content: str,
        timeout_ms: Optional[int] = None,
        correlation_id: Optional[str] = None
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Write file contents.
        Creates file if doesn't exist, overwrites if it does.
        
        Args:
            path: File path to write
            content: Content to write
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
        
        # Validate path
        allowed, path_err = self.policy.check_file_path(path, "write")
        if not allowed:
            return False, {}, path_err
        
        try:
            file_path = Path(path).resolve()
            
            # Check content size
            content_bytes = len(content.encode('utf-8'))
            if content_bytes > self.MAX_FILE_SIZE_BYTES:
                error_msg = f"Content too large: {content_bytes} bytes (max {self.MAX_FILE_SIZE_BYTES})"
                self._log_execution(
                    operation="write",
                    path=path,
                    success=False,
                    error="content_too_large",
                    content_size=content_bytes,
                    elapsed_ms=(time.time() - start_time) * 1000,
                    correlation_id=correlation_id
                )
                return False, {}, error_msg
            
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            was_existing = file_path.exists()
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Log execution
            self._log_execution(
                operation="write",
                path=path,
                success=True,
                bytes_written=content_bytes,
                was_existing=was_existing,
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            
            # Prepare result
            result_dict = {
                "path": str(file_path),
                "bytes_written": content_bytes,
                "was_existing": was_existing,
                "elapsed_ms": elapsed_ms,
                "success": True
            }
            
            return True, result_dict, None
        
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            error_msg = f"Write failed: {str(e)}"
            self._log_execution(
                operation="write",
                path=path,
                success=False,
                error=str(e),
                elapsed_ms=elapsed_ms,
                correlation_id=correlation_id
            )
            return False, {}, error_msg
    
    def _log_execution(
        self,
        operation: str,
        path: str,
        success: bool,
        error: Optional[str] = None,
        file_size: Optional[int] = None,
        bytes_written: Optional[int] = None,
        was_existing: Optional[bool] = None,
        content_size: Optional[int] = None,
        elapsed_ms: float = 0.0,
        correlation_id: Optional[str] = None
    ):
        """Log a file operation."""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "operation": operation,
            "path": path,
            "success": success,
            "elapsed_ms": elapsed_ms,
            "correlation_id": correlation_id
        }
        
        if error:
            log_entry["error"] = error
        if file_size is not None:
            log_entry["file_size"] = file_size
        if bytes_written is not None:
            log_entry["bytes_written"] = bytes_written
        if was_existing is not None:
            log_entry["was_existing"] = was_existing
        if content_size is not None:
            log_entry["content_size"] = content_size
        
        self.execution_log.append(log_entry)
    
    def get_execution_log(self) -> list[Dict[str, Any]]:
        """Get execution log."""
        return self.execution_log.copy()
    
    def clear_execution_log(self):
        """Clear execution log."""
        self.execution_log.clear()
