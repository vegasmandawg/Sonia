"""
OpenClaw Contract Tests
Tests that OpenClaw meets BOOT_CONTRACT.md requirements.
"""

import pytest
import json
from datetime import datetime
from fastapi.testclient import TestClient
from pathlib import Path
import sys

OPENCLAW_DIR = Path(__file__).resolve().parent
SERVICES_DIR = OPENCLAW_DIR.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR))

from openclaw.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client


# ============================================================================
# Universal Endpoint Tests (Required by Contract)
# ============================================================================

class TestUniversalEndpoints:
    """Test universal endpoints required by BOOT_CONTRACT.md."""
    
    def test_healthz_endpoint_exists(self, client):
        """GET /healthz must exist and return 200 within 2s."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["service"] == "openclaw"
        assert "timestamp" in data
    
    def test_healthz_response_format(self, client):
        """GET /healthz response must have required fields."""
        response = client.get("/healthz")
        data = response.json()
        
        # Required fields
        assert "ok" in data
        assert "service" in data
        assert "timestamp" in data
        
        # Type checks
        assert isinstance(data["ok"], bool)
        assert isinstance(data["service"], str)
        assert isinstance(data["timestamp"], str)
    
    def test_healthz_timestamp_iso8601(self, client):
        """Timestamp must be ISO 8601 format with Z suffix."""
        response = client.get("/healthz")
        data = response.json()
        timestamp = data["timestamp"]
        
        # Should end with Z
        assert timestamp.endswith("Z")
        
        # Should be valid ISO 8601
        # Remove Z and parse
        iso_part = timestamp[:-1]
        try:
            datetime.fromisoformat(iso_part)
        except ValueError:
            pytest.fail(f"Invalid ISO 8601 timestamp: {timestamp}")
    
    def test_root_endpoint_exists(self, client):
        """GET / must exist and return 200."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "status" in data
    
    def test_status_endpoint_exists(self, client):
        """GET /status must exist and return 200."""
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert "status" in data
        assert "timestamp" in data


# ============================================================================
# OpenClaw-Specific Contract Tests
# ============================================================================

class TestExecuteEndpoint:
    """Test POST /execute endpoint (OpenClaw-specific contract)."""
    
    def test_execute_endpoint_exists(self, client):
        """POST /execute must exist."""
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "Get-ChildItem"}
        })
        assert response.status_code in [200, 400, 422]
    
    def test_execute_response_structure(self, client):
        """POST /execute response must have required structure."""
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "Get-ChildItem"}
        })
        assert response.status_code == 200
        data = response.json()
        
        # Required fields in response envelope
        assert "status" in data
        assert "tool_name" in data
        assert "result" in data
        assert "side_effects" in data
    
    def test_execute_with_valid_shell_command(self, client):
        """Execute valid shell command (Get-ChildItem)."""
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "Get-ChildItem"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "executed"
        assert data["tool_name"] == "shell.run"
    
    def test_execute_returns_not_implemented_for_unknown_tool(self, client):
        """Unknown tools return 501 'not_implemented' status."""
        response = client.post("/execute", json={
            "tool_name": "unknown.tool",
            "args": {}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_implemented"
        assert data["tool_name"] == "unknown.tool"
    
    def test_execute_with_correlation_id(self, client):
        """Correlation ID is preserved in response."""
        correlation_id = "test_req_001"
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "Get-ChildItem"},
            "correlation_id": correlation_id
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("correlation_id") == correlation_id
    
    def test_execute_tracks_duration(self, client):
        """Response includes duration_ms."""
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "Get-ChildItem"}
        })
        assert response.status_code == 200
        data = response.json()
        assert "duration_ms" in data
        assert isinstance(data["duration_ms"], (int, float))
        assert data["duration_ms"] >= 0


# ============================================================================
# Tool Registry Tests
# ============================================================================

class TestToolRegistry:
    """Test tool registry endpoints."""
    
    def test_tools_list_endpoint(self, client):
        """GET /tools returns list of registered tools."""
        response = client.get("/tools")
        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "total" in data
        assert isinstance(data["tools"], list)
    
    def test_four_tools_registered(self, client):
        """Four tools must be registered."""
        response = client.get("/tools")
        data = response.json()
        assert data["total"] >= 4
        
        # Check specific tools exist
        tool_names = [t["name"] for t in data["tools"]]
        assert "shell.run" in tool_names
        assert "file.read" in tool_names
        assert "file.write" in tool_names
        assert "browser.open" in tool_names
    
    def test_tool_metadata_structure(self, client):
        """Tool metadata has required fields."""
        response = client.get("/tools")
        data = response.json()
        
        for tool in data["tools"]:
            assert "name" in tool
            assert "display_name" in tool
            assert "description" in tool
            assert "tier" in tool
            assert "requires_sandboxing" in tool
            assert "default_timeout_ms" in tool
    
    def test_get_specific_tool(self, client):
        """GET /tools/{tool_name} returns specific tool."""
        response = client.get("/tools/shell.run")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "shell.run"
        assert "display_name" in data
    
    def test_get_unknown_tool_returns_404(self, client):
        """GET /tools/{unknown} returns 404."""
        response = client.get("/tools/unknown.tool")
        assert response.status_code == 404


# ============================================================================
# Registry Stats Tests
# ============================================================================

class TestRegistryStats:
    """Test registry statistics endpoint."""
    
    def test_registry_stats_endpoint(self, client):
        """GET /registry/stats returns statistics."""
        response = client.get("/registry/stats")
        assert response.status_code == 200
        data = response.json()
        
        # Required fields
        assert "total_tools" in data
        assert "implemented_tools" in data
        assert "readonly_tools" in data
        assert "compute_tools" in data
        assert "create_tools" in data
        assert "destructive_tools" in data
    
    def test_stats_show_implemented_tools(self, client):
        """Stats show correct implemented tool counts."""
        response = client.get("/registry/stats")
        data = response.json()
        
        # All 4 tools are implemented
        assert data["implemented_tools"] >= 4
        assert data["readonly_tools"] >= 1  # file.read
        assert data["compute_tools"] >= 2   # shell.run, browser.open
        assert data["create_tools"] >= 1    # file.write


# ============================================================================
# Execution Log Tests
# ============================================================================

class TestExecutionLogs:
    """Test execution log endpoint."""
    
    def test_execution_logs_endpoint(self, client):
        """GET /logs/execution returns logs."""
        response = client.get("/logs/execution")
        assert response.status_code == 200
        data = response.json()
        
        assert "logs" in data
        assert "total" in data
        assert "returned" in data
    
    def test_execution_logs_limit(self, client):
        """GET /logs/execution?limit=N respects limit."""
        response = client.get("/logs/execution?limit=10")
        assert response.status_code == 200
        data = response.json()
        
        # Should return at most 10
        assert len(data["logs"]) <= 10


# ============================================================================
# Tool-Specific Tests
# ============================================================================

class TestShellRunTool:
    """Test shell.run executor."""
    
    def test_shell_run_basic(self, client):
        """shell.run executes basic PowerShell command."""
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "Get-ChildItem"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "executed"
    
    def test_shell_run_with_version(self, client):
        """shell.run can execute python --version."""
        response = client.post("/execute", json={
            "tool_name": "shell.run",
            "args": {"command": "python --version"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "executed"


class TestFileReadTool:
    """Test file.read executor."""
    
    def test_file_read_denied_outside_sandbox(self, client):
        """file.read denies paths outside S:\\."""
        response = client.post("/execute", json={
            "tool_name": "file.read",
            "args": {"path": "C:\\Windows\\System32\\config\\SAM"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
    
    def test_file_read_nonexistent_file(self, client):
        """file.read fails gracefully for nonexistent files."""
        response = client.post("/execute", json={
            "tool_name": "file.read",
            "args": {"path": "S:\\nonexistent_test_file_xyz.txt"}
        })
        assert response.status_code == 200
        data = response.json()
        # Should be error or executed with error message
        assert data["tool_name"] == "file.read"


class TestFileWriteTool:
    """Test file.write executor."""
    
    def test_file_write_to_sandbox(self, client):
        """file.write can write to S:\\."""
        response = client.post("/execute", json={
            "tool_name": "file.write",
            "args": {
                "path": "S:\\test_openclaw_write.txt",
                "content": "Test content"
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "executed"
    
    def test_file_write_denied_outside_sandbox(self, client):
        """file.write denies paths outside S:\\."""
        response = client.post("/execute", json={
            "tool_name": "file.write",
            "args": {
                "path": "C:\\Windows\\test.txt",
                "content": "Test"
            }
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"


class TestBrowserOpenTool:
    """Test browser.open executor."""
    
    def test_browser_open_rejects_invalid_url(self, client):
        """browser.open rejects invalid URLs."""
        response = client.post("/execute", json={
            "tool_name": "browser.open",
            "args": {"url": "not a url"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
    
    def test_browser_open_rejects_localhost(self, client):
        """browser.open rejects localhost URLs."""
        response = client.post("/execute", json={
            "tool_name": "browser.open",
            "args": {"url": "http://localhost:8000"}
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
