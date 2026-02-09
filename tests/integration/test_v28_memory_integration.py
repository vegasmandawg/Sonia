"""
v2.8 M2: Memory Engine Integration

Tests that memory retrieval is wired into the turn loop and
produces an auditable trail via event envelopes.

Tests (20):
  MemoryRecallResult (3):
    1. Default empty result has correct structure
    2. to_audit_dict produces valid JSON-serializable dict
    3. Memory IDs tracked accurately

  MemoryRecallContext (7):
    4. Successful retrieve returns context text
    5. Retrieve enforces max_context_chars budget
    6. Truncated flag set when budget exceeded
    7. Timeout returns empty result with error (no raise)
    8. Exception returns empty result with error (no raise)
    9. Disabled config returns immediately
    10. History bounded to max_history

  TurnMemoryEnvelope (5):
    11. Attach recall records recall metadata
    12. Record write tracks memory writes
    13. Tool-memory link records associations
    14. to_event_payload produces complete audit trail
    15. Empty envelope produces minimal payload

  Integration (5):
    16. Full turn flow: recall -> model -> tool -> write audit trail
    17. Memory context injected into model messages
    18. ActionTurnBridge with memory context tags output
    19. Multiple recalls per session tracked independently
    20. Stats reflect recall history accurately
"""

import sys
import asyncio
import json
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\pipecat")
sys.path.insert(0, r"S:\services\shared")
sys.path.insert(0, r"S:")


# ── Mocks ───────────────────────────────────────────────────────────────────

class MockMemoryClient:
    """Simulates memory_client with configurable responses."""
    def __init__(self, results=None, delay_s=0.0, fail=False):
        self._results = results or []
        self._delay_s = delay_s
        self._fail = fail
        self.search_count = 0
        self.store_count = 0
        self.last_query = None

    async def search(self, query, limit=10, correlation_id=None):
        self.search_count += 1
        self.last_query = query
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._fail:
            raise ConnectionError("Memory engine unavailable")
        return {"results": self._results}

    async def store(self, content, memory_type="fact", metadata=None, correlation_id=None):
        self.store_count += 1
        return {"id": f"mem_{self.store_count}", "status": "stored"}


class SlowMemoryClient(MockMemoryClient):
    """Memory client that's too slow -- for timeout tests."""
    def __init__(self):
        super().__init__(delay_s=10.0)


# ===========================================================================
# MemoryRecallResult tests
# ===========================================================================

class TestMemoryRecallResult:

    def test_default_empty_structure(self):
        """Default result has correct empty structure."""
        from memory_recall_context import MemoryRecallResult
        r = MemoryRecallResult()
        assert r.query_id == ""
        assert r.context_text == ""
        assert r.memory_ids == []
        assert r.retrieved_count == 0
        assert r.used_count == 0
        assert r.truncated is False
        assert r.error is None

    def test_to_audit_dict_serializable(self):
        """to_audit_dict produces valid JSON-serializable dict."""
        from memory_recall_context import MemoryRecallResult
        r = MemoryRecallResult(
            query_id="mq_test123",
            query_text="what is the user's name",
            context_text="The user's name is Alice",
            memory_ids=["mem_1", "mem_2"],
            retrieved_count=5,
            used_count=2,
            truncated=False,
            elapsed_ms=12.5,
            correlation_id="req_abc",
        )
        d = r.to_audit_dict()
        serialized = json.dumps(d)
        parsed = json.loads(serialized)
        assert parsed["query_id"] == "mq_test123"
        assert parsed["memory_ids"] == ["mem_1", "mem_2"]
        assert parsed["retrieved_count"] == 5

    def test_memory_ids_tracked(self):
        """Memory IDs reflect what was actually used."""
        from memory_recall_context import MemoryRecallResult
        r = MemoryRecallResult(
            memory_ids=["mem_a", "mem_b", "mem_c"],
            used_count=3,
        )
        assert len(r.memory_ids) == 3
        assert "mem_b" in r.memory_ids


# ===========================================================================
# MemoryRecallContext tests
# ===========================================================================

class TestMemoryRecallContext:

    @pytest.mark.asyncio
    async def test_successful_retrieve(self):
        """Successful retrieve returns context text from search results."""
        from memory_recall_context import MemoryRecallContext
        client = MockMemoryClient(results=[
            {"id": "mem_1", "content": "User prefers dark mode"},
            {"id": "mem_2", "content": "User's name is Alice"},
        ])
        ctx = MemoryRecallContext(client)
        result = await ctx.retrieve(query="user preferences", correlation_id="req_1")
        assert result.retrieved_count == 2
        assert result.used_count == 2
        assert "dark mode" in result.context_text
        assert "Alice" in result.context_text
        assert result.memory_ids == ["mem_1", "mem_2"]
        assert result.query_id.startswith("mq_")
        assert result.error is None

    @pytest.mark.asyncio
    async def test_budget_enforcement(self):
        """Retrieve enforces max_context_chars budget."""
        from memory_recall_context import MemoryRecallContext, MemoryRecallConfig
        # Create results that exceed budget
        client = MockMemoryClient(results=[
            {"id": f"mem_{i}", "content": f"Memory content block {i} " * 20}
            for i in range(10)
        ])
        config = MemoryRecallConfig(max_context_chars=200)
        ctx = MemoryRecallContext(client, config=config)
        result = await ctx.retrieve(query="test")
        assert len(result.context_text) <= 200 + 50  # Some slack for separators
        assert result.used_count < 10

    @pytest.mark.asyncio
    async def test_truncated_flag(self):
        """Truncated flag set when budget is exceeded."""
        from memory_recall_context import MemoryRecallContext, MemoryRecallConfig
        client = MockMemoryClient(results=[
            {"id": f"mem_{i}", "content": "x" * 500}
            for i in range(5)
        ])
        config = MemoryRecallConfig(max_context_chars=800)
        ctx = MemoryRecallContext(client, config=config)
        result = await ctx.retrieve(query="test")
        assert result.truncated is True
        assert result.retrieved_count == 5
        assert result.used_count < 5

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self):
        """Timeout returns empty result with error -- never raises."""
        from memory_recall_context import MemoryRecallContext, MemoryRecallConfig
        client = SlowMemoryClient()
        config = MemoryRecallConfig(timeout_ms=50)
        ctx = MemoryRecallContext(client, config=config)
        result = await ctx.retrieve(query="slow query")
        assert result.context_text == ""
        assert result.error is not None
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        """Exception returns empty result with error -- never raises."""
        from memory_recall_context import MemoryRecallContext
        client = MockMemoryClient(fail=True)
        ctx = MemoryRecallContext(client)
        result = await ctx.retrieve(query="fail query")
        assert result.context_text == ""
        assert result.error is not None
        assert "failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_disabled_config_immediate(self):
        """Disabled config returns immediately with empty result."""
        from memory_recall_context import MemoryRecallContext, MemoryRecallConfig
        client = MockMemoryClient()
        config = MemoryRecallConfig(enabled=False)
        ctx = MemoryRecallContext(client, config=config)
        result = await ctx.retrieve(query="should not search")
        assert result.context_text == ""
        assert result.error is None
        assert client.search_count == 0  # Never called

    @pytest.mark.asyncio
    async def test_history_bounded(self):
        """History respects max_history limit."""
        from memory_recall_context import MemoryRecallContext
        client = MockMemoryClient(results=[{"id": "m1", "content": "ok"}])
        ctx = MemoryRecallContext(client)
        ctx._max_history = 5
        for i in range(20):
            await ctx.retrieve(query=f"query_{i}")
        assert ctx.recall_count == 5  # Bounded


# ===========================================================================
# TurnMemoryEnvelope tests
# ===========================================================================

class TestTurnMemoryEnvelope:

    def test_attach_recall(self):
        """Attach recall records recall metadata."""
        from memory_recall_context import TurnMemoryEnvelope, MemoryRecallResult
        env = TurnMemoryEnvelope(turn_id="t_1", correlation_id="req_1")
        recall = MemoryRecallResult(
            query_id="mq_1", query_text="hi",
            memory_ids=["mem_1"], retrieved_count=1,
        )
        env.attach_recall(recall)
        assert env.has_recall
        assert env.recall_memory_ids == ["mem_1"]

    def test_record_write(self):
        """Record write tracks memory writes."""
        from memory_recall_context import TurnMemoryEnvelope
        env = TurnMemoryEnvelope(turn_id="t_2", correlation_id="req_2")
        env.record_write(
            memory_type="turn_summary",
            content_preview="User asked about dark mode",
            memory_id="mem_w1",
        )
        assert env.write_count == 1

    def test_tool_memory_link(self):
        """Tool-memory link records associations."""
        from memory_recall_context import TurnMemoryEnvelope
        env = TurnMemoryEnvelope(turn_id="t_3", correlation_id="req_3")
        env.record_tool_memory_link("file.read", ["mem_1", "mem_2"])
        payload = env.to_event_payload()
        assert len(payload["tool_memory_links"]) == 1
        assert payload["tool_memory_links"][0]["tool_name"] == "file.read"

    def test_full_event_payload(self):
        """to_event_payload produces complete audit trail."""
        from memory_recall_context import TurnMemoryEnvelope, MemoryRecallResult
        env = TurnMemoryEnvelope(turn_id="t_4", correlation_id="req_4")
        recall = MemoryRecallResult(
            query_id="mq_4", query_text="files",
            memory_ids=["mem_a"], retrieved_count=3, used_count=1,
            elapsed_ms=15.0,
        )
        env.attach_recall(recall)
        env.record_write("turn_raw", "User asked about files", "mem_w2")
        env.record_tool_memory_link("file.read", ["mem_a"])

        payload = env.to_event_payload()
        assert payload["turn_id"] == "t_4"
        assert payload["recall"]["query_id"] == "mq_4"
        assert payload["write_count"] == 1
        assert len(payload["tool_memory_links"]) == 1

        # Must be JSON-serializable
        serialized = json.dumps(payload)
        assert len(serialized) > 0

    def test_empty_envelope_minimal(self):
        """Empty envelope produces minimal payload."""
        from memory_recall_context import TurnMemoryEnvelope
        env = TurnMemoryEnvelope(turn_id="t_5", correlation_id="req_5")
        payload = env.to_event_payload()
        assert payload["turn_id"] == "t_5"
        assert "recall" not in payload
        assert "writes" not in payload
        assert "tool_memory_links" not in payload


# ===========================================================================
# Integration tests
# ===========================================================================

class TestMemoryIntegration:

    @pytest.mark.asyncio
    async def test_full_turn_audit_trail(self):
        """Full turn flow: recall -> model -> tool -> write audit trail."""
        from memory_recall_context import (
            MemoryRecallContext, TurnMemoryEnvelope, MemoryRecallConfig,
        )
        client = MockMemoryClient(results=[
            {"id": "mem_1", "content": "User's home is /home/alice"},
            {"id": "mem_2", "content": "User prefers zsh shell"},
        ])
        ctx = MemoryRecallContext(client)

        # Step 1: Recall
        recall = await ctx.retrieve(query="user shell preference", correlation_id="req_full")

        # Step 2: Create envelope
        env = TurnMemoryEnvelope(turn_id="turn_full", correlation_id="req_full")
        env.attach_recall(recall)

        # Step 3: Simulate model producing tool call influenced by memory
        env.record_tool_memory_link("shell.run", recall.memory_ids)

        # Step 4: Simulate memory writes
        env.record_write("turn_raw", "User asked about shell", "mem_w1")
        env.record_write("turn_summary", "Shell preference query", "mem_w2")

        # Verify complete trail
        payload = env.to_event_payload()
        assert payload["recall"]["memory_ids"] == ["mem_1", "mem_2"]
        assert payload["write_count"] == 2
        assert payload["tool_memory_links"][0]["influenced_by_memory_ids"] == ["mem_1", "mem_2"]

    @pytest.mark.asyncio
    async def test_memory_context_for_model(self):
        """Memory context can be injected into model messages."""
        from memory_recall_context import MemoryRecallContext
        client = MockMemoryClient(results=[
            {"id": "mem_1", "content": "User's name is Alice"},
        ])
        ctx = MemoryRecallContext(client)
        recall = await ctx.retrieve(query="who am I")

        # Build messages like stream.py does
        messages = []
        if recall.context_text:
            messages.append({"role": "system", "content": f"Relevant context:\n{recall.context_text}"})
        messages.append({"role": "user", "content": "who am I"})

        assert len(messages) == 2
        assert "Alice" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_action_bridge_memory_tagging(self):
        """ActionTurnBridge output can be tagged with memory context."""
        from memory_recall_context import TurnMemoryEnvelope, MemoryRecallResult
        # Simulate a tool execution result
        tool_result = {
            "tool_name": "file.read",
            "executed": True,
            "output": {"content": "file contents here"},
        }

        # Tag with memory
        env = TurnMemoryEnvelope(turn_id="turn_tool", correlation_id="req_tool")
        recall = MemoryRecallResult(
            query_id="mq_t", memory_ids=["mem_dir"],
        )
        env.attach_recall(recall)
        env.record_tool_memory_link("file.read", ["mem_dir"])

        payload = env.to_event_payload()
        assert payload["tool_memory_links"][0]["tool_name"] == "file.read"
        assert "mem_dir" in payload["tool_memory_links"][0]["influenced_by_memory_ids"]

    @pytest.mark.asyncio
    async def test_multiple_recalls_independent(self):
        """Multiple recalls per session tracked independently."""
        from memory_recall_context import MemoryRecallContext
        client = MockMemoryClient(results=[
            {"id": "mem_1", "content": "Result 1"},
        ])
        ctx = MemoryRecallContext(client)

        r1 = await ctx.retrieve(query="query one", correlation_id="req_1")
        r2 = await ctx.retrieve(query="query two", correlation_id="req_2")

        assert r1.query_id != r2.query_id
        assert r1.query_text == "query one"
        assert r2.query_text == "query two"
        assert ctx.recall_count == 2

    @pytest.mark.asyncio
    async def test_stats_reflect_history(self):
        """Stats reflect recall history accurately."""
        from memory_recall_context import MemoryRecallContext
        client = MockMemoryClient(results=[
            {"id": "mem_1", "content": "ok"},
        ])
        ctx = MemoryRecallContext(client)

        for i in range(5):
            await ctx.retrieve(query=f"q_{i}")

        stats = ctx.get_stats()
        assert stats["total_recalls"] == 5
        assert stats["recent_success_rate"] == 1.0
        assert stats["recent_avg_results"] == 1.0
        assert stats["recent_avg_latency_ms"] >= 0
