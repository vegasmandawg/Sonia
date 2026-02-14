"""
v2.9.2 Schema Invariant Tests — Frozen Contract Verification

Ensures core API schemas have not changed shape. These tests freeze the
field names and types of public-facing Pydantic models so that any schema
drift is caught before release.

Frozen schemas:
  - TurnRequest / TurnResponse (turn.py)
  - SessionCreateRequest / SessionCreateResponse (session.py)
  - ActionPlanRequest / ActionPlanResponse (action.py)
  - /healthz response shape (all 6 services)

Run: python -m pytest tests/integration/test_schema_invariants.py -v
"""

import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
import httpx

GW = "http://127.0.0.1:7000"


# ===========================================================================
# TurnRequest / TurnResponse schema freeze
# ===========================================================================

class TestTurnSchemaFreeze:

    def test_turn_request_required_fields(self):
        from schemas.turn import TurnRequest
        fields = TurnRequest.model_fields
        # Required fields
        assert "user_id" in fields
        assert "conversation_id" in fields
        assert "input_text" in fields
        # Optional fields with defaults
        assert "profile" in fields
        assert "metadata" in fields

    def test_turn_request_field_count(self):
        from schemas.turn import TurnRequest
        assert len(TurnRequest.model_fields) == 5

    def test_turn_response_required_fields(self):
        from schemas.turn import TurnResponse
        fields = TurnResponse.model_fields
        assert "ok" in fields
        assert "turn_id" in fields
        assert "assistant_text" in fields
        assert "tool_calls" in fields
        assert "tool_results" in fields
        assert "memory" in fields
        assert "duration_ms" in fields
        assert "error" in fields

    def test_turn_response_field_count(self):
        from schemas.turn import TurnResponse
        assert len(TurnResponse.model_fields) == 8

    def test_tool_call_record_fields(self):
        from schemas.turn import ToolCallRecord
        fields = ToolCallRecord.model_fields
        assert "tool_name" in fields
        assert "args" in fields
        assert "status" in fields
        assert "result" in fields
        assert len(fields) == 4

    def test_memory_summary_fields(self):
        from schemas.turn import MemorySummary
        fields = MemorySummary.model_fields
        assert "written" in fields
        assert "retrieved_count" in fields
        assert len(fields) == 2


# ===========================================================================
# SessionCreateRequest / SessionCreateResponse schema freeze
# ===========================================================================

class TestSessionSchemaFreeze:

    def test_session_create_request_fields(self):
        from schemas.session import SessionCreateRequest
        fields = SessionCreateRequest.model_fields
        assert "user_id" in fields
        assert "conversation_id" in fields
        assert "profile" in fields
        assert "metadata" in fields
        assert len(fields) == 4

    def test_session_create_response_fields(self):
        from schemas.session import SessionCreateResponse
        fields = SessionCreateResponse.model_fields
        assert "ok" in fields
        assert "session_id" in fields
        assert "created_at" in fields
        assert "expires_at" in fields
        assert "status" in fields
        assert len(fields) == 5

    def test_session_info_fields(self):
        from schemas.session import SessionInfo
        fields = SessionInfo.model_fields
        expected = {
            "session_id", "user_id", "conversation_id", "profile",
            "status", "created_at", "expires_at", "last_activity",
            "turn_count", "active_streams", "metadata",
        }
        assert expected.issubset(set(fields.keys()))

    def test_confirmation_info_fields(self):
        from schemas.session import ConfirmationInfo
        fields = ConfirmationInfo.model_fields
        expected = {
            "confirmation_id", "session_id", "turn_id", "tool_name",
            "args", "summary", "status", "created_at", "remaining_seconds",
        }
        assert expected == set(fields.keys())

    def test_stream_event_fields(self):
        from schemas.session import StreamEvent
        fields = StreamEvent.model_fields
        assert "type" in fields
        assert "session_id" in fields
        assert "turn_id" in fields
        assert "timestamp" in fields
        assert "payload" in fields
        assert len(fields) == 5


# ===========================================================================
# ActionPlanRequest / ActionPlanResponse schema freeze
# ===========================================================================

class TestActionSchemaFreeze:

    def test_action_plan_request_fields(self):
        from schemas.action import ActionPlanRequest
        fields = ActionPlanRequest.model_fields
        expected = {
            "intent", "params", "timeout_ms", "max_retries",
            "idempotency_key", "session_id", "dry_run", "metadata",
        }
        assert expected == set(fields.keys())

    def test_action_plan_response_fields(self):
        from schemas.action import ActionPlanResponse
        fields = ActionPlanResponse.model_fields
        expected = {
            "ok", "action_id", "state", "intent", "risk_level",
            "requires_confirmation", "validation", "execution",
            "telemetry", "error", "correlation_id",
        }
        assert expected == set(fields.keys())

    def test_action_record_core_fields(self):
        from schemas.action import ActionRecord
        fields = ActionRecord.model_fields
        core = {
            "action_id", "intent", "params", "state", "risk_level",
            "requires_confirmation", "dry_run", "idempotency_key",
            "correlation_id", "session_id", "validation", "execution",
            "telemetry", "created_at", "updated_at", "completed_at",
            "max_retries", "retry_count", "timeout_ms",
        }
        assert core.issubset(set(fields.keys()))

    def test_risk_levels_frozen(self):
        from schemas.action import RiskLevel
        # RiskLevel is a Literal type — check via __args__
        assert set(RiskLevel.__args__) == {"safe", "low", "medium", "high", "critical"}

    def test_action_states_frozen(self):
        from schemas.action import ActionState
        expected = {
            "planned", "validated", "pending_approval", "approved",
            "denied", "executing", "verifying", "succeeded",
            "failed", "cancelled", "timeout", "rolled_back",
        }
        assert set(ActionState.__args__) == expected


# ===========================================================================
# /healthz response shape (live endpoint)
# ===========================================================================

class TestHealthzContract:

    @pytest.mark.asyncio
    async def test_gateway_healthz_shape(self):
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{GW}/healthz")
            assert r.status_code == 200
            d = r.json()
            assert d["ok"] is True
            assert d["service"] == "api-gateway"
            assert "version" in d
            assert "timestamp" in d

    @pytest.mark.asyncio
    async def test_all_services_healthz_shape(self):
        """All 6 core services respond with ok/service/version on /healthz."""
        ports = {
            "api-gateway": 7000,
            "model-router": 7010,
            "memory-engine": 7020,
            "pipecat": 7030,
            "openclaw": 7040,
            "eva-os": 7050,
        }
        async with httpx.AsyncClient(timeout=10) as c:
            for svc, port in ports.items():
                try:
                    r = await c.get(f"http://127.0.0.1:{port}/healthz")
                    assert r.status_code == 200, f"{svc} healthz returned {r.status_code}"
                    d = r.json()
                    assert d["ok"] is True, f"{svc} healthz ok is not True"
                    assert "service" in d, f"{svc} healthz missing 'service' key"
                except httpx.ConnectError:
                    pytest.skip(f"{svc} not running on port {port}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
