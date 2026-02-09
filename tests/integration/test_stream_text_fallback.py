"""
Stage 3 — WebSocket stream with text fallback integration tests.
Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_stream_text_fallback.py -v
"""
import pytest, httpx, uuid, json, asyncio
from websockets.client import connect as ws_connect

GW = "http://127.0.0.1:7000"
GW_WS = "ws://127.0.0.1:7000"
TIMEOUT = 60.0


async def _create_session():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GW}/v1/sessions", json={
            "user_id": "test-user",
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        })
        return r.json()["session_id"]


class TestStreamTextFallback:

    @pytest.mark.asyncio
    async def test_ws_connect_and_ack(self):
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            ev = json.loads(raw)
            assert ev["type"] == "ack"
            assert ev["payload"]["status"] == "connected"

    @pytest.mark.asyncio
    async def test_input_text_gets_response_final(self):
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            # consume ack
            await asyncio.wait_for(ws.recv(), timeout=5)
            # send input.text
            await ws.send(json.dumps({
                "type": "input.text",
                "session_id": sid,
                "payload": {"text": "What is 2 plus 2?"},
            }))
            # collect events until response.final
            got_final = False
            for _ in range(10):
                raw = await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)
                ev = json.loads(raw)
                if ev["type"] == "response.final":
                    got_final = True
                    assert len(ev["payload"]["assistant_text"]) > 0
                    break
            assert got_final, "Never received response.final"

    @pytest.mark.asyncio
    async def test_ping_pong(self):
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            await ws.send(json.dumps({"type": "control.ping"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            ev = json.loads(raw)
            assert ev["type"] == "ack"
            assert ev["payload"]["pong"] is True

    @pytest.mark.asyncio
    async def test_invalid_session_returns_error(self):
        async with ws_connect(f"{GW_WS}/v1/stream/ses_bogus") as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            ev = json.loads(raw)
            assert ev["type"] == "error"
            assert ev["payload"]["code"] == "SESSION_NOT_FOUND"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
