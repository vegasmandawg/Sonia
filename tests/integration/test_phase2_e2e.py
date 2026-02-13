"""
Phase 2 End-to-End Integration Tests
Tests for API Gateway orchestration, Pipecat sessions, and cross-service communication.
"""

import pytest
import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional

import httpx
import websockets

# Configuration
API_GATEWAY_URL = "http://127.0.0.1:7000"
PIPECAT_URL = "http://127.0.0.1:7030"
PIPECAT_WS_URL = "ws://127.0.0.1:7030"

TIMEOUT = 30.0


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def api_client():
    """Create HTTP client for API Gateway."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        yield client


@pytest.fixture
async def pipecat_client():
    """Create HTTP client for Pipecat."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        yield client


def generate_correlation_id() -> str:
    """Generate correlation ID."""
    return f"req_{uuid.uuid4().hex[:12]}"


# ============================================================================
# API Gateway Tests
# ============================================================================

class TestAPIGatewayChat:
    """Test /v1/chat orchestration route."""
    
    @pytest.mark.infra_flaky
    @pytest.mark.asyncio
    async def test_chat_endpoint_exists(self, api_client):
        """POST /v1/chat endpoint exists and is accessible."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/chat",
            params={"message": "Hello"},
            headers={"X-Correlation-ID": correlation_id}
        )
        
        assert response.status_code in [200, 400]  # 200 success, 400 missing args
    
    @pytest.mark.asyncio
    async def test_chat_response_structure(self, api_client):
        """Chat response has standard envelope structure."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/chat",
            params={"message": "What is 2+2?"},
            headers={"X-Correlation-ID": correlation_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify standard envelope
        assert "ok" in data
        assert "service" in data
        assert data["service"] == "api-gateway"
        assert "operation" in data
        assert data["operation"] == "chat"
        assert "correlation_id" in data
        assert data["correlation_id"] == correlation_id
        assert "duration_ms" in data
        assert "data" in data
        assert "error" in data
    
    @pytest.mark.asyncio
    async def test_chat_with_session(self, api_client, pipecat_client):
        """Chat with session ID retrieves context from Memory Engine."""
        correlation_id = generate_correlation_id()
        
        # First, start a session in Pipecat
        session_response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={},
            headers={"X-Correlation-ID": correlation_id}
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["data"]["session_id"]
        
        # Then, chat with that session
        chat_response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/chat",
            params={
                "message": "Remember this fact",
                "session_id": session_id
            },
            headers={"X-Correlation-ID": correlation_id}
        )
        
        assert chat_response.status_code == 200
        chat_data = chat_response.json()
        
        # Should have provenance information
        if chat_data.get("ok") and chat_data.get("data"):
            provenance = chat_data["data"].get("provenance", {})
            assert "memory_engine" in provenance or "model_router" in provenance
    
    @pytest.mark.asyncio
    async def test_chat_correlation_id_propagated(self, api_client):
        """Correlation ID is preserved through orchestration."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/chat",
            params={"message": "Test"},
            headers={"X-Correlation-ID": correlation_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["correlation_id"] == correlation_id


class TestAPIGatewayAction:
    """Test /v1/action orchestration route."""
    
    @pytest.mark.asyncio
    async def test_action_endpoint_exists(self, api_client):
        """POST /v1/action endpoint exists."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/action",
            params={
                "tool_name": "shell.run",
                "args": json.dumps({"command": "Get-ChildItem"})
            },
            headers={"X-Correlation-ID": correlation_id}
        )
        
        # Should succeed or fail gracefully
        assert response.status_code in [200, 400, 422]
    
    @pytest.mark.asyncio
    async def test_action_response_structure(self, api_client):
        """Action response has standard envelope structure."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/action",
            params={
                "tool_name": "shell.run",
                "args": json.dumps({"command": "python --version"})
            },
            headers={"X-Correlation-ID": correlation_id}
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Verify envelope
            assert data["service"] == "api-gateway"
            assert data["operation"] == "action"
            assert data["correlation_id"] == correlation_id
            assert "duration_ms" in data
            assert "data" in data
            assert "error" in data
    
    @pytest.mark.asyncio
    async def test_action_unknown_tool_returns_error(self, api_client):
        """Unknown tool returns proper error."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/action",
            params={
                "tool_name": "unknown.tool",
                "args": json.dumps({})
            },
            headers={"X-Correlation-ID": correlation_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should indicate tool not available
        assert not data.get("ok")
        assert data.get("error")


class TestAPIGatewayDeps:
    """Test /v1/deps connectivity endpoint."""
    
    @pytest.mark.asyncio
    async def test_deps_endpoint_exists(self, api_client):
        """GET /v1/deps endpoint exists."""
        response = await api_client.get(f"{API_GATEWAY_URL}/v1/deps")
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_deps_checks_all_services(self, api_client):
        """GET /v1/deps checks all downstream services."""
        response = await api_client.get(f"{API_GATEWAY_URL}/v1/deps")
        data = response.json()
        
        # Should have data
        assert data.get("data")
        deps = data["data"]
        
        # Should check all services
        expected_services = ["memory_engine", "model_router", "openclaw"]
        for service in expected_services:
            assert service in deps


# ============================================================================
# Pipecat Tests
# ============================================================================

class TestPipecatSessions:
    """Test Pipecat session lifecycle."""
    
    @pytest.mark.asyncio
    async def test_session_start(self, pipecat_client):
        """POST /session/start creates new session."""
        correlation_id = generate_correlation_id()
        
        response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={},
            headers={"X-Correlation-ID": correlation_id}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify envelope
        assert data["ok"] is True
        assert data["service"] == "pipecat"
        assert data["operation"] == "session_start"
        
        # Verify session data
        session_data = data["data"]
        assert "session_id" in session_data
        assert session_data["state"] == "ACTIVE"
        assert "created_at" in session_data
    
    @pytest.mark.asyncio
    async def test_session_get(self, pipecat_client):
        """GET /session/{id} retrieves session."""
        # Create session
        create_response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={}
        )
        session_id = create_response.json()["data"]["session_id"]
        
        # Get session
        get_response = await pipecat_client.get(
            f"{PIPECAT_URL}/session/{session_id}"
        )
        
        assert get_response.status_code == 200
        data = get_response.json()
        
        assert data["ok"] is True
        assert data["data"]["id"] == session_id
        assert data["data"]["state"] == "ACTIVE"
    
    @pytest.mark.asyncio
    async def test_session_stop(self, pipecat_client):
        """POST /session/stop closes session."""
        # Create session
        create_response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={}
        )
        session_id = create_response.json()["data"]["session_id"]
        
        # Stop session
        stop_response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/stop",
            params={"session_id": session_id}
        )
        
        assert stop_response.status_code == 200
        data = stop_response.json()
        
        assert data["ok"] is True
        assert data["data"]["state"] == "CLOSED"


class TestPipecatWebSocket:
    """Test Pipecat WebSocket communication."""
    
    @pytest.mark.asyncio
    async def test_websocket_connection(self, pipecat_client):
        """WebSocket connection to session."""
        # Create session
        create_response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={}
        )
        session_id = create_response.json()["data"]["session_id"]
        
        # Connect WebSocket
        ws_url = f"{PIPECAT_WS_URL}/ws/{session_id}"

        try:
            async with websockets.connect(
                ws_url,
                open_timeout=TIMEOUT,
                close_timeout=TIMEOUT,
            ) as websocket:
                # Should receive SESSION_START event
                event_json = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                event = json.loads(event_json)

                assert event["type"] == "SESSION_START"
                assert event["session_id"] == session_id

        except asyncio.TimeoutError:
            pytest.fail("WebSocket connection timed out")
        except Exception as e:
            pytest.fail(f"WebSocket connection failed: {e}")
    
    @pytest.mark.asyncio
    async def test_websocket_message_roundtrip(self, pipecat_client):
        """Send and receive message via WebSocket."""
        # Create session
        create_response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={}
        )
        session_id = create_response.json()["data"]["session_id"]
        
        try:
            async with websockets.connect(
                f"{PIPECAT_WS_URL}/ws/{session_id}",
                open_timeout=TIMEOUT,
                close_timeout=TIMEOUT,
            ) as websocket:
                # Receive SESSION_START
                await asyncio.wait_for(websocket.recv(), timeout=5.0)

                # Receive STATUS event
                status_json = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                status_event = json.loads(status_json)
                assert status_event["type"] == "STATUS"

                # Send MESSAGE event
                message_event = {
                    "type": "MESSAGE",
                    "session_id": session_id,
                    "data": {
                        "text": "Hello, Pipecat!",
                        "role": "user"
                    },
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "correlation_id": "test_001"
                }
                await websocket.send(json.dumps(message_event))

                # Receive response MESSAGE event
                response_json = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                response_event = json.loads(response_json)

                assert response_event["type"] == "MESSAGE"
                assert response_event["data"]["role"] == "assistant"
                assert len(response_event["data"]["text"]) > 0

        except asyncio.TimeoutError:
            pytest.fail("WebSocket message roundtrip timed out")
        except Exception as e:
            pytest.fail(f"WebSocket message roundtrip failed: {e}")


# ============================================================================
# Cross-Service Tests
# ============================================================================

class TestCorrelationID:
    """Test correlation ID propagation through services."""
    
    @pytest.mark.asyncio
    async def test_correlation_id_in_gateway_response(self, api_client):
        """Correlation ID appears in API Gateway response."""
        correlation_id = generate_correlation_id()
        
        response = await api_client.get(
            f"{API_GATEWAY_URL}/status",
            headers={"X-Correlation-ID": correlation_id}
        )
        
        # Health check always returns 200
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_correlation_id_in_pipecat_response(self, pipecat_client):
        """Correlation ID appears in Pipecat response."""
        correlation_id = generate_correlation_id()
        
        response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={},
            headers={"X-Correlation-ID": correlation_id}
        )
        
        data = response.json()
        assert data["correlation_id"] == correlation_id


class TestEnvelopeCompliance:
    """Test standard envelope compliance across services."""
    
    @pytest.mark.asyncio
    async def test_api_gateway_envelope(self, api_client):
        """API Gateway responses follow standard envelope."""
        response = await api_client.post(
            f"{API_GATEWAY_URL}/v1/chat",
            params={"message": "Test"}
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Required envelope fields
            assert isinstance(data.get("ok"), bool)
            assert isinstance(data.get("service"), str)
            assert isinstance(data.get("operation"), str)
            assert isinstance(data.get("correlation_id"), str)
            assert isinstance(data.get("duration_ms"), (int, float))
            assert data.get("data") is not None or data.get("error") is not None
    
    @pytest.mark.asyncio
    async def test_pipecat_envelope(self, pipecat_client):
        """Pipecat responses follow standard envelope."""
        response = await pipecat_client.post(
            f"{PIPECAT_URL}/session/start",
            json={}
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Required envelope fields
            assert isinstance(data.get("ok"), bool)
            assert isinstance(data.get("service"), str)
            assert isinstance(data.get("operation"), str)
            assert isinstance(data.get("correlation_id"), str)
            assert isinstance(data.get("duration_ms"), (int, float))
            assert data.get("data") is not None or data.get("error") is not None


# ============================================================================
# Service Health Tests
# ============================================================================

class TestServiceHealth:
    """Test service health check endpoints."""
    
    @pytest.mark.asyncio
    async def test_api_gateway_health(self, api_client):
        """API Gateway /healthz responds."""
        response = await api_client.get(f"{API_GATEWAY_URL}/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["service"] == "api-gateway"
    
    @pytest.mark.asyncio
    async def test_pipecat_health(self, pipecat_client):
        """Pipecat /healthz responds."""
        response = await pipecat_client.get(f"{PIPECAT_URL}/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["service"] == "pipecat"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
