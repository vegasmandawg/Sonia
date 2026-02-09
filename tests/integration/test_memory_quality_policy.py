"""
Stage 4 — Memory quality policy integration tests.
Verifies summary+raw write tags, retrieval returns bounded context,
and memory failure is non-fatal (memory.written=false).

Run: S:\\envs\\sonia-core\\python.exe -m pytest tests/integration/test_memory_quality_policy.py -v
"""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest, httpx, uuid, json, asyncio

GW = "http://127.0.0.1:7000"
TIMEOUT = 120.0


class TestMemoryQualityPolicy:
    """Memory write/retrieval policy behavior."""

    @pytest.mark.asyncio
    async def test_turn_writes_memory_with_ok_true(self):
        """Turn with ok=true should have memory.written=true."""
        marker = f"mempol_{uuid.uuid4().hex[:8]}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/turn", json={
                "user_id": "memtest",
                "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
                "input_text": f"Memory policy test marker {marker}",
            })
            d = r.json()
            assert d["ok"] is True
            assert d["memory"]["written"] is True

    @pytest.mark.asyncio
    async def test_retrieval_returns_bounded_context(self):
        """Subsequent turn should retrieve bounded context."""
        conv_id = f"conv_{uuid.uuid4().hex[:8]}"
        marker = f"xyzzy_{uuid.uuid4().hex[:6]}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # First turn stores data
            r1 = await c.post(f"{GW}/v1/turn", json={
                "user_id": "memtest",
                "conversation_id": conv_id,
                "input_text": f"Remember the code word {marker} for later",
            })
            assert r1.json()["ok"] is True

            # Second turn should retrieve
            r2 = await c.post(f"{GW}/v1/turn", json={
                "user_id": "memtest",
                "conversation_id": conv_id,
                "input_text": marker,
            })
            d2 = r2.json()
            assert d2["ok"] is True
            assert d2["memory"]["retrieved_count"] >= 1

    @pytest.mark.asyncio
    async def test_memory_failure_is_non_fatal(self):
        """Even if memory write fails, response should still have ok=true.
        We can't easily force a memory failure in integration, but we verify
        that the response envelope correctly reports memory state."""
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(f"{GW}/v1/turn", json={
                "user_id": "memtest-nonfatal",
                "conversation_id": f"conv_{uuid.uuid4().hex[:8]}",
                "input_text": "Verify non-fatal memory path",
            })
            d = r.json()
            # The turn should succeed regardless of memory outcome
            assert d["ok"] is True
            assert "memory" in d
            assert "written" in d["memory"]


class TestMemoryPolicyUnit:
    """Unit tests for memory policy module."""

    def test_build_summary_truncates(self):
        from memory_policy import _build_summary
        long_input = "x" * 200
        long_output = "y" * 200
        summary = _build_summary(long_input, long_output)
        assert len(summary) < 300  # should be truncated
        assert "User:" in summary
        assert "Assistant:" in summary

    @pytest.mark.asyncio
    async def test_retrieve_context_returns_dict(self):
        from memory_policy import retrieve_context
        from clients.memory_client import MemoryClient
        mc = MemoryClient(base_url="http://127.0.0.1:7020")
        try:
            result = await retrieve_context(mc, "test query")
            assert "context_text" in result
            assert "retrieved_count" in result
            assert "truncated" in result
        finally:
            await mc.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
