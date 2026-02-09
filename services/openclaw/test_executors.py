"""
OpenClaw Executor Unit Tests
Test individual executors in isolation.
"""

import pytest
import tempfile
from pathlib import Path
import os

from .executors.shell_exec import ShellExecutor
from .executors.file_exec import FileExecutor
from .executors.browser_exec import BrowserExecutor
from .policy import ExecutionPolicy, FilesystemSandbox, ShellCommandAllowlist


# ============================================================================
# Shell Executor Tests
# ============================================================================

class TestShellExecutor:
    """Unit tests for ShellExecutor."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.executor = ShellExecutor()
    
    def test_shell_execute_valid_command(self):
        """Execute valid allowlisted command."""
        success, result, error = self.executor.execute("Get-ChildItem")
        assert success is True
        assert error is None
        assert "return_code" in result
        assert "stdout" in result
        assert "stderr" in result
    
    def test_shell_execute_command_with_args(self):
        """Execute command with arguments."""
        success, result, error = self.executor.execute("Get-ChildItem -Path S:\\")
        assert success is True
        assert error is None
    
    def test_shell_execute_forbidden_command(self):
        """Reject forbidden command (Remove-Item)."""
        success, result, error = self.executor.execute("Remove-Item -Path S:\\test.txt")
        assert success is False
        assert error is not None
        assert "not in allowlist" in error
    
    def test_shell_execute_with_timeout(self):
        """Execute with custom timeout."""
        success, result, error = self.executor.execute(
            "Get-ChildItem",
            timeout_ms=10000
        )
        assert success is True
        assert result["elapsed_ms"] > 0
    
    def test_shell_execute_timeout_exceeded(self):
        """Reject timeout > max_timeout."""
        success, result, error = self.executor.execute(
            "Get-ChildItem",
            timeout_ms=20000  # Exceeds MAX_TIMEOUT_MS=15000
        )
        assert success is False
        assert "exceeds maximum" in error
    
    def test_shell_execution_logged(self):
        """Execution is logged."""
        self.executor.clear_execution_log()
        self.executor.execute("Get-ChildItem")
        logs = self.executor.get_execution_log()
        assert len(logs) > 0
        assert logs[0]["command"] == "Get-ChildItem"
        assert logs[0]["success"] is True
    
    def test_shell_correlation_id_tracked(self):
        """Correlation ID is tracked in logs."""
        self.executor.clear_execution_log()
        self.executor.execute(
            "Get-ChildItem",
            correlation_id="test_001"
        )
        logs = self.executor.get_execution_log()
        assert logs[0]["correlation_id"] == "test_001"


# ============================================================================
# File Executor Tests
# ============================================================================

class TestFileExecutor:
    """Unit tests for FileExecutor."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.executor = FileExecutor()
        self.test_dir = Path("S:\\test_openclaw_temp")
        self.test_dir.mkdir(exist_ok=True)
    
    def teardown_method(self):
        """Clean up test files."""
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_file_read_success(self):
        """Read existing file."""
        # Create test file
        test_file = self.test_dir / "test_read.txt"
        test_file.write_text("Test content")
        
        # Read it
        success, result, error = self.executor.read(str(test_file))
        assert success is True
        assert error is None
        assert result["content"] == "Test content"
        assert result["size_bytes"] > 0
    
    def test_file_read_nonexistent(self):
        """Read nonexistent file."""
        success, result, error = self.executor.read(
            str(self.test_dir / "nonexistent.txt")
        )
        assert success is False
        assert error is not None
        assert "not found" in error.lower()
    
    def test_file_read_outside_sandbox(self):
        """Read outside sandbox is denied."""
        success, result, error = self.executor.read("C:\\Windows\\System32\\config\\SAM")
        assert success is False
        assert error is not None
        assert "sandbox" in error.lower()
    
    def test_file_write_success(self):
        """Write file successfully."""
        test_file = self.test_dir / "test_write.txt"
        content = "New content"
        
        success, result, error = self.executor.write(str(test_file), content)
        assert success is True
        assert error is None
        assert result["bytes_written"] == len(content.encode('utf-8'))
        
        # Verify file was written
        assert test_file.exists()
        assert test_file.read_text() == content
    
    def test_file_write_creates_parent_dirs(self):
        """Write creates parent directories."""
        test_file = self.test_dir / "subdir" / "nested" / "test.txt"
        
        success, result, error = self.executor.write(str(test_file), "Content")
        assert success is True
        assert test_file.exists()
    
    def test_file_write_overwrite(self):
        """Write overwrites existing file."""
        test_file = self.test_dir / "test_overwrite.txt"
        test_file.write_text("Original")
        
        success, result, error = self.executor.write(str(test_file), "New")
        assert success is True
        assert test_file.read_text() == "New"
        assert result["was_existing"] is True
    
    def test_file_write_outside_sandbox(self):
        """Write outside sandbox is denied."""
        success, result, error = self.executor.write(
            "C:\\Windows\\test.txt",
            "Content"
        )
        assert success is False
        assert error is not None
        assert "sandbox" in error.lower()
    
    def test_file_operations_logged(self):
        """File operations are logged."""
        test_file = self.test_dir / "test_log.txt"
        self.executor.clear_execution_log()
        
        self.executor.write(str(test_file), "Content")
        self.executor.read(str(test_file))
        
        logs = self.executor.get_execution_log()
        assert len(logs) == 2
        assert logs[0]["operation"] == "write"
        assert logs[1]["operation"] == "read"


# ============================================================================
# Browser Executor Tests
# ============================================================================

class TestBrowserExecutor:
    """Unit tests for BrowserExecutor."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.executor = BrowserExecutor()
    
    def test_browser_open_valid_url(self):
        """Open valid HTTPS URL."""
        # Note: This will attempt to open browser
        # In test environment, may return True or False depending on system
        success, result, error = self.executor.open("https://www.example.com")
        # Either succeeds or fails gracefully
        assert isinstance(success, bool)
    
    def test_browser_open_invalid_scheme(self):
        """Reject FTP scheme."""
        success, result, error = self.executor.open("ftp://example.com")
        assert success is False
        assert error is not None
        assert "scheme" in error.lower()
    
    def test_browser_open_localhost_blocked(self):
        """Block localhost URLs."""
        success, result, error = self.executor.open("http://localhost:8000")
        assert success is False
        assert error is not None
        assert "blocked" in error.lower()
    
    def test_browser_open_127_0_0_1_blocked(self):
        """Block 127.0.0.1."""
        success, result, error = self.executor.open("http://127.0.0.1:8000")
        assert success is False
        assert error is not None
    
    def test_browser_open_invalid_url(self):
        """Reject invalid URL."""
        success, result, error = self.executor.open("not a url")
        assert success is False
        assert error is not None
    
    def test_browser_operations_logged(self):
        """Browser operations are logged."""
        self.executor.clear_execution_log()
        self.executor.open("https://www.example.com")
        
        logs = self.executor.get_execution_log()
        assert len(logs) >= 1
        assert logs[0]["operation"] == "open"


# ============================================================================
# Policy Tests
# ============================================================================

class TestExecutionPolicy:
    """Unit tests for ExecutionPolicy."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.policy = ExecutionPolicy()
    
    def test_allow_valid_command(self):
        """Allow valid command."""
        allowed, reason = self.policy.check_shell_command("Get-ChildItem")
        assert allowed is True
        assert reason is None
    
    def test_deny_forbidden_command(self):
        """Deny forbidden command."""
        allowed, reason = self.policy.check_shell_command("Remove-Item")
        assert allowed is False
        assert reason is not None
    
    def test_allow_file_in_sandbox(self):
        """Allow file in sandbox."""
        allowed, reason = self.policy.check_file_path("S:\\test.txt", "read")
        assert allowed is True
        assert reason is None
    
    def test_deny_file_outside_sandbox(self):
        """Deny file outside sandbox."""
        allowed, reason = self.policy.check_file_path("C:\\Windows\\test.txt", "read")
        assert allowed is False
        assert reason is not None
    
    def test_timeout_within_limits(self):
        """Allow timeout within limits."""
        allowed, reason = self.policy.check_timeout(5000)
        assert allowed is True
        assert reason is None
    
    def test_timeout_exceeds_max(self):
        """Deny timeout exceeding maximum."""
        allowed, reason = self.policy.check_timeout(20000, max_timeout_ms=15000)
        assert allowed is False
        assert reason is not None
        assert "exceeds" in reason.lower()
    
    def test_denied_operations_logged(self):
        """Denied operations are logged."""
        self.policy.clear_denied_log()
        self.policy.check_shell_command("Remove-Item")
        self.policy.check_file_path("C:\\test.txt", "read")
        
        assert self.policy.get_denied_count() == 2


# ============================================================================
# Allowlist Tests
# ============================================================================

class TestShellCommandAllowlist:
    """Unit tests for ShellCommandAllowlist."""
    
    def test_get_childitem_allowed(self):
        """Get-ChildItem is allowed."""
        assert ShellCommandAllowlist.is_allowed("Get-ChildItem") is True
    
    def test_get_content_allowed(self):
        """Get-Content is allowed."""
        assert ShellCommandAllowlist.is_allowed("Get-Content") is True
    
    def test_test_path_allowed(self):
        """Test-Path is allowed."""
        assert ShellCommandAllowlist.is_allowed("Test-Path") is True
    
    def test_remove_item_denied(self):
        """Remove-Item is denied."""
        assert ShellCommandAllowlist.is_allowed("Remove-Item") is False
    
    def test_delete_denied(self):
        """Delete is denied."""
        assert ShellCommandAllowlist.is_allowed("Delete") is False
    
    def test_command_with_args_checks_command_only(self):
        """Command with args checks command part only."""
        assert ShellCommandAllowlist.is_allowed("Get-ChildItem -Path S:\\") is True
        assert ShellCommandAllowlist.is_allowed("Remove-Item -Path S:\\") is False


# ============================================================================
# Filesystem Sandbox Tests
# ============================================================================

class TestFilesystemSandbox:
    """Unit tests for FilesystemSandbox."""
    
    def test_s_drive_is_safe(self):
        """S:\\ is safe."""
        assert FilesystemSandbox.is_path_safe("S:\\test.txt") is True
    
    def test_s_subdir_is_safe(self):
        """S:\\subdir is safe."""
        assert FilesystemSandbox.is_path_safe("S:\\subdir\\file.txt") is True
    
    def test_c_drive_is_unsafe(self):
        """C:\\ is unsafe."""
        assert FilesystemSandbox.is_path_safe("C:\\test.txt") is False
    
    def test_windows_dir_is_blocked(self):
        """S:\\Windows is blocked."""
        assert FilesystemSandbox.is_path_safe("S:\\Windows\\test.txt") is False
    
    def test_get_safe_path_returns_path_if_safe(self):
        """get_safe_path returns Path if safe."""
        result = FilesystemSandbox.get_safe_path("S:\\test.txt")
        assert result is not None
        assert isinstance(result, Path)
    
    def test_get_safe_path_returns_none_if_unsafe(self):
        """get_safe_path returns None if unsafe."""
        result = FilesystemSandbox.get_safe_path("C:\\test.txt")
        assert result is None
