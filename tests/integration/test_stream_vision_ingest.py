"""
Stage 4 — Vision ingestion integration tests.
Tests that vision frames are accepted/rejected correctly through
the WebSocket stream protocol.

Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_stream_vision_ingest.py -v
"""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest, httpx, uuid, json, asyncio, base64
from websockets.client import connect as ws_connect

GW = "http://127.0.0.1:7000"
GW_WS = "ws://127.0.0.1:7000"
TIMEOUT = 30.0

# Create a tiny valid 1x1 PNG (67 bytes)
TINY_PNG_B64 = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
    b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
    b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
    b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
).decode()

# Create a base64 string that decodes to > 1MB (oversized)
OVERSIZED_B64 = base64.b64encode(b'\x00' * (1_048_576 + 100)).decode()


async def _create_session():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GW}/v1/sessions", json={
            "user_id": "test-vision",
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        })
        return r.json()["session_id"]


class TestVisionIngest:
    """Test vision frame acceptance/rejection via WebSocket."""

    @pytest.mark.asyncio
    async def test_vision_accepted_with_valid_frame(self):
        """Valid PNG frame after enabling vision should be accepted."""
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            # Read ack
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ack["type"] == "ack"

            # Enable vision
            await ws.send(json.dumps({
                "type": "control.vision.enable",
                "payload": {},
            }))
            enable_ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert enable_ack["type"] == "ack"
            assert enable_ack["payload"]["vision_enabled"] is True

            # Send a valid frame
            await ws.send(json.dumps({
                "type": "input.vision.frame",
                "payload": {
                    "frame_id": "frm_test001",
                    "mime_type": "image/png",
                    "data": TINY_PNG_B64,
                },
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp["type"] == "vision.accepted"
            assert resp["payload"]["frame_id"] == "frm_test001"
            assert resp["payload"]["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_vision_rejected_oversize_frame(self):
        """Oversized frame should be rejected but session stays alive."""
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ack["type"] == "ack"

            # Enable vision
            await ws.send(json.dumps({
                "type": "control.vision.enable",
                "payload": {},
            }))
            json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

            # Send oversize frame
            await ws.send(json.dumps({
                "type": "input.vision.frame",
                "payload": {
                    "frame_id": "frm_toobig",
                    "mime_type": "image/png",
                    "data": OVERSIZED_B64,
                },
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp["type"] == "vision.rejected"
            assert resp["payload"]["code"] == "FRAME_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_session_alive_after_invalid_frame(self):
        """Session should remain usable after a rejected frame."""
        sid = await _create_session()
        async with ws_connect(f"{GW_WS}/v1/stream/{sid}") as ws:
            ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert ack["type"] == "ack"

            # Enable vision
            await ws.send(json.dumps({
                "type": "control.vision.enable",
                "payload": {},
            }))
            json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

            # Send invalid mime
            await ws.send(json.dumps({
                "type": "input.vision.frame",
                "payload": {
                    "frame_id": "frm_bad",
                    "mime_type": "application/pdf",
                    "data": TINY_PNG_B64,
                },
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert resp["type"] == "vision.rejected"
            assert resp["payload"]["code"] == "INVALID_MIME_TYPE"

            # Session still works — send a ping
            await ws.send(json.dumps({"type": "control.ping"}))
            pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            assert pong["type"] == "ack"
            assert pong["payload"]["pong"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
