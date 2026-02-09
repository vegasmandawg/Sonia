"""
Stage 3 — Stage 2 compatibility regression tests.
Verifies that all Stage 2 behaviour still works after Stage 3 additions.

Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_stage2_compat.py -v
"""
import pytest, httpx, uuid

GW = "http://127.0.0.1:7000"
TIMEOUT = 60.0


def _turn_payload(text="What is 2 plus 2?"):
    return {
        "user_id": "compat-test",
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "input_text": text,
        "profile": "chat_low_latency",
    }


class TestStage2Compat:

    @pytest.mark.asyncio
    async def test_healthz_still_works(self):
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{GW}/healthz")
            assert r.status_code == 200
            assert r.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_turn_returns_200(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/turn", json=_turn_payload())
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_turn_has_assistant_text(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/turn", json=_turn_payload())
            d = r.json()
            assert d["ok"] is True
            assert len(d["assistant_text"]) > 0

    @pytest.mark.asyncio
    async def test_turn_has_turn_id(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/turn", json=_turn_payload())
            d = r.json()
            assert d["turn_id"].startswith("turn_")

    @pytest.mark.asyncio
    async def test_turn_has_memory(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/turn", json=_turn_payload())
            d = r.json()
            assert "memory" in d
            assert isinstance(d["memory"]["written"], bool)

    @pytest.mark.asyncio
    async def test_chat_endpoint_still_works(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(
                f"{GW}/v1/chat",
                params={"message": "Hello"},
            )
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_deps_endpoint_still_works(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{GW}/v1/deps")
            assert r.status_code == 200
            d = r.json()
            assert "data" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
