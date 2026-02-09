"""
v2.7 M4 Integration Tests -- Action Execution Bridge

Tests the ActionTurnBridge that connects the turn pipeline's
tool-call execution to the full Stage 5 action pipeline
(plan -> validate -> execute -> verify).

Tests (20):
  ToolExecutionResult (3):
    1. Default result is not-executed, not-pending, not-rejected
    2. Executed result has output and side_effects
    3. Pending result carries action_id

  ActionTurnBridge basic (6):
    4. Execute safe tool -> succeeded
    5. Execute unknown tool -> rejected (validation fail)
    6. Dry run -> validated, not executed
    7. Guarded tool -> pending_approval
    8. Idempotency key returns same action
    9. Pipeline exception -> BRIDGE_ERROR

  ActionTurnBridge batch (3):
    10. Batch of 3 tools executes all sequentially
    11. Batch with mixed results (1 ok, 1 fail)
    12. Empty batch returns empty list

  Approval flow (4):
    13. Approve pending -> succeeded
    14. Deny pending -> rejected
    15. Approve non-existent -> error
    16. Deny non-existent -> error

  Pipeline integration (4):
    17. Full round-trip: bridge -> pipeline -> mock openclaw -> result
    18. Circuit breaker open -> dead-lettered failure
    19. Retries exhausted -> failure with retries_used
    20. Stats endpoint returns pipeline_available
"""

import sys
import asyncio
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

import pytest

sys.path.insert(0, r"S:\services\api-gateway")


# ── Mock OpenClaw client ────────────────────────────────────────────────────

class MockOpenclawClient:
    """Simulates OpenClaw execution for testing."""

    def __init__(self):
        self.calls: List[Dict] = []
        self.next_result: Optional[Dict] = None
        self.fail_with: Optional[Exception] = None
        self.call_count = 0

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        timeout_ms: int = 5000,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.call_count += 1
        self.calls.append({
            "tool_name": tool_name,
            "args": args,
            "timeout_ms": timeout_ms,
            "correlation_id": correlation_id,
        })
        if self.fail_with:
            raise self.fail_with
        if self.next_result:
            return self.next_result
        return {
            "status": "executed",
            "result": {"mock": True, "tool": tool_name},
            "side_effects": [],
        }


# ── Mock breaker registry ──────────────────────────────────────────────────

class MockBreaker:
    """Minimal circuit breaker mock."""

    def __init__(self, open_circuit=False):
        self._open = open_circuit

    class _State:
        def __init__(self, val):
            self.value = val

    @property
    def state(self):
        return self._State("open" if self._open else "closed")

    async def call(self, fn):
        if self._open:
            from circuit_breaker import CircuitOpenError
            raise CircuitOpenError("openclaw", "open")
        return await fn()


class MockBreakerRegistry:
    def __init__(self, open_circuit=False):
        self._breakers = {}
        self._open = open_circuit

    def get_or_create(self, name):
        if name not in self._breakers:
            self._breakers[name] = MockBreaker(self._open)
        return self._breakers[name]

    def get(self, name):
        return self._breakers.get(name)


# ── Mock DLQ ────────────────────────────────────────────────────────────────

class MockDeadLetterQueue:
    def __init__(self):
        self.letters = []

    async def enqueue(self, **kwargs):
        self.letters.append(kwargs)

    async def list_letters(self, **kwargs):
        return self.letters

    async def get(self, letter_id):
        return None


# ── Mock Audit Logger ───────────────────────────────────────────────────────

class _MockTrail:
    def __init__(self):
        self.events = []

    def record(self, *args, **kwargs):
        self.events.append((args, kwargs))


class MockAuditLogger:
    def __init__(self):
        self.trails = {}

    def create_trail(self, action_id, intent, correlation_id=None):
        t = _MockTrail()
        self.trails[action_id] = t
        return t

    def flush_trail(self, action_id):
        pass

    def get_trail(self, action_id):
        return self.trails.get(action_id)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_pipeline(openclaw=None, open_circuit=False):
    """Create an ActionPipeline with mocked dependencies."""
    import action_audit
    import dead_letter

    # Patch singletons
    mock_audit = MockAuditLogger()
    action_audit._audit_logger = mock_audit

    oc = openclaw or MockOpenclawClient()
    breakers = MockBreakerRegistry(open_circuit=open_circuit)
    dlq = MockDeadLetterQueue()

    from action_pipeline import ActionPipeline
    pipeline = ActionPipeline(
        openclaw_client=oc,
        breaker_registry=breakers,
        dead_letter_queue=dlq,
    )
    return pipeline, oc, breakers, dlq, mock_audit


def _make_bridge(openclaw=None, open_circuit=False):
    """Create an ActionTurnBridge with mocked pipeline."""
    from action_turn_bridge import ActionTurnBridge
    pipeline, oc, breakers, dlq, audit = _make_pipeline(
        openclaw=openclaw, open_circuit=open_circuit
    )
    bridge = ActionTurnBridge(pipeline)
    return bridge, oc, dlq, audit


# ===========================================================================
# ToolExecutionResult tests
# ===========================================================================

class TestToolExecutionResult:

    def test_default_result(self):
        from action_turn_bridge import ToolExecutionResult
        r = ToolExecutionResult()
        assert r.executed is False
        assert r.pending_approval is False
        assert r.rejected is False
        assert r.output == {}
        assert r.action_id == ""
        assert r.error == ""

    def test_executed_result(self):
        from action_turn_bridge import ToolExecutionResult
        r = ToolExecutionResult(
            tool_name="file.read",
            executed=True,
            output={"content": "hello"},
            side_effects=["fs_read"],
        )
        assert r.executed is True
        assert r.output == {"content": "hello"}
        assert r.side_effects == ["fs_read"]

    def test_pending_result(self):
        from action_turn_bridge import ToolExecutionResult
        r = ToolExecutionResult(
            tool_name="shell.run",
            pending_approval=True,
            action_id="act_abc123",
        )
        assert r.pending_approval is True
        assert r.action_id == "act_abc123"
        assert r.executed is False


# ===========================================================================
# ActionTurnBridge basic tests
# ===========================================================================

class TestActionTurnBridgeBasic:

    @pytest.mark.asyncio
    async def test_execute_safe_tool(self):
        """file.read is safe (no confirm) -> succeeds immediately."""
        bridge, oc, dlq, audit = _make_bridge()
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/test.txt"},
            session_id="sess-1",
            correlation_id="req_test1",
        )
        assert r.executed is True
        assert r.action_state == "succeeded"
        assert r.risk_level == "safe"
        assert r.output.get("mock") is True
        assert oc.call_count == 1

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        """Unknown intent fails validation."""
        bridge, oc, dlq, audit = _make_bridge()
        r = await bridge.execute_tool_call(
            tool_name="nonexistent.tool",
            tool_args={},
            correlation_id="req_test2",
        )
        assert r.rejected is True
        assert r.executed is False
        assert "VALIDATION_FAILED" in r.error_code or "unknown" in r.error.lower()
        assert oc.call_count == 0  # Never reached openclaw

    @pytest.mark.asyncio
    async def test_dry_run(self):
        """Dry run validates but does not execute."""
        bridge, oc, dlq, audit = _make_bridge()
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/test.txt"},
            dry_run=True,
            correlation_id="req_test3",
        )
        assert r.dry_run is True
        assert r.executed is False
        assert r.action_state == "validated"
        assert oc.call_count == 0

    @pytest.mark.asyncio
    async def test_guarded_tool_pending(self):
        """shell.run requires confirmation -> pending_approval."""
        bridge, oc, dlq, audit = _make_bridge()
        r = await bridge.execute_tool_call(
            tool_name="shell.run",
            tool_args={"command": "ls"},
            session_id="sess-1",
            correlation_id="req_test4",
        )
        assert r.pending_approval is True
        assert r.executed is False
        assert r.action_id.startswith("act_")
        assert oc.call_count == 0

    @pytest.mark.asyncio
    async def test_idempotency_key(self):
        """Same idempotency key returns same action_id both times."""
        bridge, oc, dlq, audit = _make_bridge()
        r1 = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/test.txt"},
            idempotency_key="idem-1",
            correlation_id="req_test5a",
        )
        r2 = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/test.txt"},
            idempotency_key="idem-1",
            correlation_id="req_test5b",
        )
        # Both runs return the same action record (plan phase is idempotent)
        assert r1.action_id == r2.action_id
        assert r1.executed is True
        assert r2.executed is True

    @pytest.mark.asyncio
    async def test_pipeline_exception(self):
        """Pipeline exception is caught and returned as BRIDGE_ERROR."""
        from action_turn_bridge import ActionTurnBridge

        class BrokenPipeline:
            async def run(self, req, correlation_id=""):
                raise RuntimeError("Pipeline exploded")

        bridge = ActionTurnBridge(BrokenPipeline())
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={},
            correlation_id="req_test6",
        )
        assert r.executed is False
        assert r.error_code == "BRIDGE_ERROR"
        assert "exploded" in r.error


# ===========================================================================
# ActionTurnBridge batch tests
# ===========================================================================

class TestActionTurnBridgeBatch:

    @pytest.mark.asyncio
    async def test_batch_of_3(self):
        """Batch executes all tool calls sequentially."""
        bridge, oc, dlq, audit = _make_bridge()
        calls = [
            {"tool_name": "file.read", "args": {"path": "/a"}},
            {"tool_name": "file.read", "args": {"path": "/b"}},
            {"tool_name": "file.read", "args": {"path": "/c"}},
        ]
        results = await bridge.execute_batch(
            tool_calls=calls,
            session_id="sess-1",
            correlation_id="req_batch1",
        )
        assert len(results) == 3
        assert all(r.executed for r in results)
        assert oc.call_count == 3

    @pytest.mark.asyncio
    async def test_batch_mixed_results(self):
        """Batch with one valid and one unknown tool."""
        bridge, oc, dlq, audit = _make_bridge()
        calls = [
            {"tool_name": "file.read", "args": {"path": "/a"}},
            {"tool_name": "nonexistent.tool", "args": {}},
        ]
        results = await bridge.execute_batch(
            tool_calls=calls,
            session_id="sess-1",
            correlation_id="req_batch2",
        )
        assert len(results) == 2
        assert results[0].executed is True
        assert results[1].rejected is True

    @pytest.mark.asyncio
    async def test_batch_empty(self):
        """Empty batch returns empty list."""
        bridge, oc, dlq, audit = _make_bridge()
        results = await bridge.execute_batch(
            tool_calls=[],
            correlation_id="req_batch3",
        )
        assert results == []


# ===========================================================================
# Approval flow tests
# ===========================================================================

class TestApprovalFlow:

    @pytest.mark.asyncio
    async def test_approve_pending(self):
        """Approve a pending guarded action -> executed."""
        bridge, oc, dlq, audit = _make_bridge()
        # First, create a pending action
        r1 = await bridge.execute_tool_call(
            tool_name="shell.run",
            tool_args={"command": "ls"},
            session_id="sess-1",
            correlation_id="req_approve1",
        )
        assert r1.pending_approval is True
        action_id = r1.action_id

        # Approve it
        r2 = await bridge.approve_pending(action_id)
        assert r2.executed is True
        assert r2.action_state == "succeeded"

    @pytest.mark.asyncio
    async def test_deny_pending(self):
        """Deny a pending guarded action -> rejected."""
        bridge, oc, dlq, audit = _make_bridge()
        r1 = await bridge.execute_tool_call(
            tool_name="shell.run",
            tool_args={"command": "rm -rf"},
            session_id="sess-1",
            correlation_id="req_deny1",
        )
        assert r1.pending_approval is True
        action_id = r1.action_id

        r2 = await bridge.deny_pending(action_id)
        assert r2.rejected is True
        assert r2.action_state == "denied"

    @pytest.mark.asyncio
    async def test_approve_nonexistent(self):
        """Approve a non-existent action_id -> error."""
        bridge, oc, dlq, audit = _make_bridge()
        r = await bridge.approve_pending("act_doesnotexist")
        assert r.executed is False
        # Either rejected or error
        assert r.rejected is True or r.error != ""

    @pytest.mark.asyncio
    async def test_deny_nonexistent(self):
        """Deny a non-existent action_id -> error."""
        bridge, oc, dlq, audit = _make_bridge()
        r = await bridge.deny_pending("act_doesnotexist")
        assert r.rejected is True


# ===========================================================================
# Pipeline integration tests
# ===========================================================================

class TestPipelineIntegration:

    @pytest.mark.asyncio
    async def test_full_roundtrip(self):
        """Full: bridge -> pipeline -> mock openclaw -> result with telemetry."""
        oc = MockOpenclawClient()
        oc.next_result = {
            "status": "executed",
            "result": {"data": "hello world"},
            "side_effects": ["disk_read"],
        }
        bridge, _, dlq, audit = _make_bridge(openclaw=oc)
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/etc/passwd"},
            session_id="sess-rt",
            correlation_id="req_rt1",
        )
        assert r.executed is True
        assert r.output == {"data": "hello world"}
        assert r.side_effects == ["disk_read"]
        assert r.duration_ms >= 0  # mock executes instantly

    @pytest.mark.asyncio
    async def test_circuit_breaker_open(self):
        """Open circuit breaker -> failure + dead-lettered."""
        bridge, oc, dlq, audit = _make_bridge(open_circuit=True)
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/x"},
            correlation_id="req_cb1",
        )
        assert r.rejected is True
        assert r.executed is False
        assert "CIRCUIT_OPEN" in r.error_code or "circuit" in r.error.lower()
        # DLQ should have the dead letter
        assert len(dlq.letters) == 1

    @pytest.mark.asyncio
    async def test_retries_exhausted(self):
        """Openclaw returns error, retries exhaust -> failure."""
        oc = MockOpenclawClient()
        oc.next_result = {"status": "error", "error": "service down"}
        bridge, _, dlq, audit = _make_bridge(openclaw=oc)
        r = await bridge.execute_tool_call(
            tool_name="file.read",
            tool_args={"path": "/tmp/x"},
            max_retries=1,
            correlation_id="req_retry1",
        )
        assert r.rejected is True
        assert r.executed is False
        assert oc.call_count == 2  # 1 initial + 1 retry
        # Should be dead-lettered
        assert len(dlq.letters) == 1

    @pytest.mark.asyncio
    async def test_stats_endpoint(self):
        """Stats returns pipeline_available."""
        bridge, oc, dlq, audit = _make_bridge()
        stats = bridge.get_stats()
        assert stats["pipeline_available"] is True
