"""
Integration tests for the /v1/turn end-to-end pipeline.

Assumes the full Sonia stack is already running on localhost:
  api-gateway  7000
  model-router 7010
  memory-engine 7020
  pipecat      7030
  openclaw     7040
  eva-os       7050

Run:
    S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_turn_pipeline.py -v
"""

import pytest
import httpx
import uuid

API_GATEWAY = "http://127.0.0.1:7000"
TIMEOUT = 60.0  # model inference can be slow on first call


def _correlation_id() -> str:
    return f"test_{uuid.uuid4().hex[:10]}"


def _turn_payload(text: str = "What is 2 plus 2?") -> dict:
    return {
        "user_id": "test-user",
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "input_text": text,
        "profile": "chat_low_latency",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Pre-flight: stack must be healthy
# ──────────────────────────────────────────────────────────────────────────────

class TestPreflight:
    """Verify the stack is up before running turn tests."""

    @pytest.mark.asyncio
    async def test_gateway_healthy(self):
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{API_GATEWAY}/healthz")
            assert r.status_code == 200
            assert r.json()["ok"] is True


# ──────────────────────────────────────────────────────────────────────────────
# Core turn tests
# ──────────────────────────────────────────────────────────────────────────────

class TestTurnEndpoint:
    """Test the /v1/turn orchestration endpoint."""

    @pytest.mark.asyncio
    async def test_turn_returns_200(self):
        """Basic call returns HTTP 200."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                f"{API_GATEWAY}/v1/turn",
                json=_turn_payload(),
                headers={"X-Correlation-ID": _correlation_id()},
            )
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_turn_response_shape(self):
        """Response has the required fields: ok, turn_id, assistant_text, memory."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                f"{API_GATEWAY}/v1/turn",
                json=_turn_payload(),
                headers={"X-Correlation-ID": _correlation_id()},
            )
            data = r.json()
            assert data["ok"] is True
            assert data["turn_id"].startswith("turn_")
            assert isinstance(data["assistant_text"], str)
            assert len(data["assistant_text"]) > 0, "assistant_text must be non-empty"
            assert "memory" in data
            assert isinstance(data["memory"]["written"], bool)
            assert isinstance(data["memory"]["retrieved_count"], int)

    @pytest.mark.asyncio
    async def test_turn_id_is_unique(self):
        """Two calls produce different turn_ids."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r1 = await c.post(f"{API_GATEWAY}/v1/turn", json=_turn_payload())
            r2 = await c.post(f"{API_GATEWAY}/v1/turn", json=_turn_payload())
            assert r1.json()["turn_id"] != r2.json()["turn_id"]

    @pytest.mark.asyncio
    async def test_memory_written_on_turn(self):
        """Turn should persist to memory-engine."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                f"{API_GATEWAY}/v1/turn",
                json=_turn_payload("Remember that the sky is blue."),
            )
            data = r.json()
            assert data["ok"] is True
            assert data["memory"]["written"] is True

    @pytest.mark.asyncio
    async def test_second_call_retrieves_memory(self):
        """
        A second call whose input_text is a substring of the first turn's
        stored content should retrieve at least one memory.

        Note: memory-engine uses SQL LIKE %query% matching, so the second
        query must be a literal substring of the stored turn content.
        """
        conv_id = f"conv_{uuid.uuid4().hex[:8]}"
        marker = f"xyzzy_{uuid.uuid4().hex[:6]}"
        payload_1 = {
            "user_id": "test-user",
            "conversation_id": conv_id,
            "input_text": f"Remember the code word {marker} for later.",
            "profile": "chat_low_latency",
        }
        payload_2 = {
            "user_id": "test-user",
            "conversation_id": conv_id,
            "input_text": marker,
            "profile": "chat_low_latency",
        }
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r1 = await c.post(f"{API_GATEWAY}/v1/turn", json=payload_1)
            assert r1.json()["ok"] is True
            assert r1.json()["memory"]["written"] is True

            r2 = await c.post(f"{API_GATEWAY}/v1/turn", json=payload_2)
            data2 = r2.json()
            assert data2["ok"] is True
            # The second call should have retrieved the record containing the marker
            assert data2["memory"]["retrieved_count"] >= 1

    @pytest.mark.asyncio
    async def test_missing_input_text_returns_422(self):
        """Missing required field returns validation error."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                f"{API_GATEWAY}/v1/turn",
                json={"user_id": "x", "conversation_id": "y"},
            )
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_duration_is_positive(self):
        """Response includes a positive duration_ms."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{API_GATEWAY}/v1/turn", json=_turn_payload())
            data = r.json()
            assert data.get("duration_ms", 0) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
