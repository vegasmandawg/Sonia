"""
Stage 4 — Stage 3 compatibility regression tests.
Confirms that Stage 3 session/stream/tool confirmation still
behaves exactly as before after Stage 4 changes.

Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_stage3_compat.py -v
"""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest, httpx, uuid, json, asyncio
from websockets.client import connect as ws_connect

GW = "http://127.0.0.1:7000"
GW_WS = "ws://127.0.0.1:7000"
TIMEOUT = 120.0


async def _create_session():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GW}/v1/sessions", json={
            "user_id": "s3compat",
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        })
        return r.json()["session_id"]


class TestStage3Compat:
    """Verify Stage 3 behavior is preserved."""

    @pytest.mark.asyncio
    async def test_session_create_returns_ses_id(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/sessions", json={
                "user_id": "s3compat",
                "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
            })
            d = r.json()
            assert d["ok"] is True
            assert d["session_id"].startswith("ses_")

    @pytest.mark.asyncio
    async def test_session_get_returns_active(self):
        sid = await _create_session()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{GW}/v1/sessions/{sid}")
            d = r.json()
            assert d["status"] == "active"

    @pytest.mark.asyncio
    async def test_session_delete_works(self):
        sid = await _create_session()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.delete(f"{GW}/v1/sessions/{sid}")
            d = r.json()
            assert d["ok"] is True

    @pytest.mark.asyncio
    async def test_ws_connect_gets_ack(self):
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ack["type"] == "ack"
            assert ack["payload"]["status"] == "connected"

    @pytest.mark.asyncio
    async def test_ws_text_gets_response_final(self):
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            await ws.send(json.dumps({
                "type": "input.text",
                "payload": {"text": "Stage 3 compat: what is 4+4?"},
            }))
            for _ in range(10):
                ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=TIMEOUT))
                if ev["type"] == "response.final":
                    assert ev["payload"].get("assistant_text")
                    return
            pytest.fail("No response.final received")

    @pytest.mark.asyncio
    async def test_confirmation_pending_returns_empty(self):
        sid = await _create_session()
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{GW}/v1/confirmations/pending", params={"session_id": sid})
            d = r.json()
            assert d["ok"] is True
            assert d["count"] == 0

    @pytest.mark.asyncio
    async def test_ping_pong_still_works(self):
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            await ws.send(json.dumps({"type": "control.ping"}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert pong["type"] == "ack"
            assert pong["payload"]["pong"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
