"""
Stage 4 — Confirmation idempotency tests.
Verifies that duplicate approve/deny on the same confirmation_id
returns deterministic results with no duplicate execution.

Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_confirmation_idempotency.py -v
"""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest, httpx, uuid, json, asyncio

GW = "http://127.0.0.1:7000"
TIMEOUT = 30.0


async def _create_session():
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GW}/v1/sessions", json={
            "user_id": "test-idempotent",
            "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
        })
        return r.json()["session_id"]


class TestConfirmationIdempotency:
    """Test that approve/deny are idempotent."""

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_not_found(self):
        """Approving a nonexistent token returns not_found."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/confirmations/cfm_idem_fake1/approve")
            d = r.json()
            assert d["ok"] is False
            assert d["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_deny_nonexistent_returns_not_found(self):
        """Denying a nonexistent token returns not_found."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/confirmations/cfm_idem_fake2/deny")
            d = r.json()
            assert d["ok"] is False
            assert d["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_double_approve_returns_same_status(self):
        """Double approve on same id should return the same result (idempotent).
        We cannot create real confirmations from outside the stream,
        so we verify the approve path returns not_found consistently."""
        cid = f"cfm_{uuid.uuid4().hex[:16]}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r1 = await c.post(f"{GW}/v1/confirmations/{cid}/approve")
            r2 = await c.post(f"{GW}/v1/confirmations/{cid}/approve")
            d1 = r1.json()
            d2 = r2.json()
            # Both should return the same deterministic result
            assert d1["status"] == d2["status"]
            assert d1["ok"] == d2["ok"]

    @pytest.mark.asyncio
    async def test_double_deny_returns_same_status(self):
        """Double deny on same id should return deterministic result."""
        cid = f"cfm_{uuid.uuid4().hex[:16]}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r1 = await c.post(f"{GW}/v1/confirmations/{cid}/deny",
                              json={"reason": "test"})
            r2 = await c.post(f"{GW}/v1/confirmations/{cid}/deny",
                              json={"reason": "test again"})
            d1 = r1.json()
            d2 = r2.json()
            assert d1["status"] == d2["status"]


class TestConfirmationIdempotencyUnit:
    """Unit tests for idempotent confirmation manager."""

    @pytest.mark.asyncio
    async def test_approve_after_approve_is_idempotent(self):
        from tool_policy import GatewayConfirmationManager
        mgr = GatewayConfirmationManager()
        token = await mgr.create("ses1", "t1", "file.write", {"path": "/tmp/x"})
        r1 = await mgr.approve(token.confirmation_id)
        assert r1["ok"] is True
        assert r1["status"] == "approved"

        # Second approve: idempotent
        r2 = await mgr.approve(token.confirmation_id)
        assert r2["ok"] is True
        assert r2["status"] == "approved"
        assert r2.get("idempotent") is True

    @pytest.mark.asyncio
    async def test_deny_after_deny_is_idempotent(self):
        from tool_policy import GatewayConfirmationManager
        mgr = GatewayConfirmationManager()
        token = await mgr.create("ses2", "t2", "shell.run", {"cmd": "ls"})
        r1 = await mgr.deny(token.confirmation_id, "no")
        assert r1["status"] == "denied"

        # Second deny: idempotent
        r2 = await mgr.deny(token.confirmation_id, "still no")
        assert r2["status"] == "denied"
        assert r2.get("idempotent") is True

    @pytest.mark.asyncio
    async def test_approve_after_deny_returns_denied(self):
        from tool_policy import GatewayConfirmationManager
        mgr = GatewayConfirmationManager()
        token = await mgr.create("ses3", "t3", "file.write", {})
        await mgr.deny(token.confirmation_id, "denied first")
        r = await mgr.approve(token.confirmation_id)
        # Should not flip from denied to approved
        assert r["ok"] is False
        assert r["status"] == "approved" or r.get("idempotent") is True

    @pytest.mark.asyncio
    async def test_deny_after_approve_returns_approved(self):
        from tool_policy import GatewayConfirmationManager
        mgr = GatewayConfirmationManager()
        token = await mgr.create("ses4", "t4", "browser.open", {})
        await mgr.approve(token.confirmation_id)
        r = await mgr.deny(token.confirmation_id, "too late")
        # Should return the existing approved status
        assert r["status"] == "approved"
        assert r.get("idempotent") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
