"""
Stage 3 — Session lifecycle integration tests.
Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_session_lifecycle.py -v
"""
import pytest, httpx, uuid

GW = "http://127.0.0.1:7000"
TIMEOUT = 30.0


def _body():
    return {
        "user_id": "test-user",
        "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        "profile": "chat_low_latency",
    }


class TestSessionLifecycle:

    @pytest.mark.asyncio
    async def test_create_session(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/sessions", json=_body())
            assert r.status_code == 200
            d = r.json()
            assert d["ok"] is True
            assert d["session_id"].startswith("ses_")
            assert d["status"] == "active"
            assert "created_at" in d
            assert "expires_at" in d

    @pytest.mark.asyncio
    async def test_get_session(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            cr = await c.post(f"{GW}/v1/sessions", json=_body())
            sid = cr.json()["session_id"]
            r = await c.get(f"{GW}/v1/sessions/{sid}")
            assert r.status_code == 200
            d = r.json()
            assert d["ok"] is True
            assert d["session_id"] == sid
            assert d["status"] == "active"

    @pytest.mark.asyncio
    async def test_delete_session(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            cr = await c.post(f"{GW}/v1/sessions", json=_body())
            sid = cr.json()["session_id"]
            r = await c.delete(f"{GW}/v1/sessions/{sid}")
            assert r.status_code == 200
            d = r.json()
            assert d["ok"] is True
            assert d["session_id"] == sid
            assert "closed_at" in d

    @pytest.mark.asyncio
    async def test_get_after_delete_shows_closed(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            cr = await c.post(f"{GW}/v1/sessions", json=_body())
            sid = cr.json()["session_id"]
            await c.delete(f"{GW}/v1/sessions/{sid}")
            r = await c.get(f"{GW}/v1/sessions/{sid}")
            d = r.json()
            assert d["status"] == "closed"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_error(self):
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"{GW}/v1/sessions/ses_nonexistent")
            d = r.json()
            assert d["ok"] is False
            assert d["error"]["code"] == "SESSION_NOT_FOUND"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
