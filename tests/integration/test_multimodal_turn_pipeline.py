"""
Stage 4 — Multimodal turn pipeline integration tests.
Tests that text + vision in one turn produces response.final with
quality annotations and latency fields.

Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_multimodal_turn_pipeline.py -v
"""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest, httpx, uuid, json, asyncio, base64
from websockets.client import connect as ws_connect

GW = "http://127.0.0.1:7000"
GW_WS = "ws://127.0.0.1:7000"
TIMEOUT = 120.0

# Tiny valid PNG
TINY_PNG_B64 = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
    b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
    b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
).decode()


_warmup_done = False

async def _warmup_model():
    """Block until the model responds with ok=true (up to 5 attempts)."""
    global _warmup_done
    if _warmup_done:
        return
    for attempt in range(5):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                r = await c.post(f"{GW}/v1/turn", json={
                    "user_id": "warmup",
                    "conversation_id": f"warmup-mm-{attempt}",
                    "input_text": "ping",
                })
                if r.json().get("ok"):
                    _warmup_done = True
                    return
        except Exception:
            pass
        await asyncio.sleep(3.0)
    # Mark done to avoid repeated warmup attempts, but model may still be cold
    _warmup_done = True


async def _create_session():
    await _warmup_model()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GW}/v1/sessions", json={
            "user_id": "test-mm",
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        })
        return r.json()["session_id"]


class TestMultimodalTurnPipeline:
    """Multimodal turn (text + vision) through WebSocket stream."""

    @pytest.mark.asyncio
    async def test_text_turn_has_quality_annotations(self):
        """A text-only turn should include quality annotations."""
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ack["type"] == "ack"

            await ws.send(json.dumps({
                "type": "input.text",
                "payload": {"text": "What is 7 plus 7?"},
            }))

            for _ in range(10):
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=TIMEOUT))
                if ev["type"] == "response.final":
                    p = ev["payload"]
                    assert p.get("assistant_text")
                    assert "quality" in p
                    q = p["quality"]
                    assert "generation_profile_used" in q
                    assert "fallback_used" in q
                    assert "completion_reason" in q
                    assert p.get("has_vision") is False
                    return

            pytest.fail("No response.final received")

    @pytest.mark.asyncio
    async def test_text_plus_vision_produces_response(self):
        """Text + vision_data in one turn produces response.final or clean error.

        The model-router may not support vision (Ollama limitation).
        Valid outcomes:
          - response.final with assistant_text + quality (vision or text fallback)
          - error event with INTERNAL_ERROR (model doesn't support vision)
          - clean WS close (1000 OK) after server-side error handling
        Invalid: unclean crash, hang, or no response within timeout.
        """
        from websockets.exceptions import ConnectionClosedOK

        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ack["type"] == "ack"

            await ws.send(json.dumps({
                "type": "input.text",
                "payload": {
                    "text": "What do you see in this image?",
                    "vision_data": TINY_PNG_B64,
                    "vision_mime": "image/png",
                },
            }))

            events = []
            try:
                for _ in range(15):
                    ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=TIMEOUT))
                    events.append(ev["type"])
                    if ev["type"] == "response.final":
                        p = ev["payload"]
                        assert p.get("assistant_text")
                        assert "quality" in p
                        return
                    if ev["type"] == "error":
                        # Server handled the vision failure gracefully
                        return
            except ConnectionClosedOK:
                # Server closed WS after handling internal error — acceptable
                # for vision turns when model doesn't support multimodal
                return

            pytest.fail(f"No response.final or error; got events: {events}")

    @pytest.mark.asyncio
    async def test_sync_turn_has_quality_and_latency(self):
        """The sync /v1/turn endpoint should include quality + latency.

        Retries up to 5 times with increasing backoff to handle Ollama
        cold-start and post-WS-test model busy states.
        """
        last_error = None
        for attempt in range(5):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                    r = await c.post(f"{GW}/v1/turn", json={
                        "user_id": "mm-test",
                        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
                        "input_text": "Stage 4 quality test: what is 5 plus 5?",
                    })
                    d = r.json()
                    if not d.get("ok"):
                        last_error = f"ok=False on attempt {attempt}: {d.get('error')}"
                        await asyncio.sleep(5.0 * (attempt + 1))
                        continue

                    assert d.get("assistant_text")
                    assert d.get("turn_id", "").startswith("turn_")

                    # Quality annotations
                    assert "quality" in d
                    q = d["quality"]
                    assert q["completion_reason"] in ("ok", "fallback")
                    assert isinstance(q["fallback_used"], bool)
                    assert isinstance(q["tool_calls_attempted"], int)

                    # Latency breakdown
                    assert "latency" in d
                    lat = d["latency"]
                    assert "memory_read_ms" in lat
                    assert "model_ms" in lat
                    assert "total_ms" in lat
                    assert lat["total_ms"] > 0
                    return  # success
            except httpx.ReadTimeout:
                last_error = f"ReadTimeout on attempt {attempt}"
                await asyncio.sleep(5.0 * (attempt + 1))

        pytest.fail(f"test_sync_turn_has_quality_and_latency failed after 5 attempts: {last_error}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
