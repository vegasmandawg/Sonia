"""Unit tests for router_client fallback behavior — M3 conservative gap closer."""
import os, sys, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))

from clients.router_client import (
    RouterClient, RouterClientError,
    FALLBACK_CONTRACT_VERSION, FALLBACK_TRIGGERS,
)


def run(coro):
    """Helper to run async tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_fallback(client=None, **kwargs):
    """Helper: get a fallback result from an unreachable router."""
    if client is None:
        client = RouterClient(base_url="http://127.0.0.1:19999", timeout=0.5)
    result = run(client.chat_with_fallback(
        messages=[{"role": "user", "content": "hello"}],
        **kwargs,
    ))
    run(client.close())
    return result


class TestFallbackContract:
    """Verify the fallback response envelope is machine-detectable."""

    def test_source_field(self):
        result = _make_fallback()
        assert result["source"] == "fallback"

    def test_fallback_trigger_is_enum(self):
        result = _make_fallback()
        assert result["fallback_trigger"] in FALLBACK_TRIGGERS

    def test_contract_version_present(self):
        result = _make_fallback()
        assert result["fallback_contract_version"] == FALLBACK_CONTRACT_VERSION

    def test_all_required_keys_present(self):
        result = _make_fallback()
        required = {
            "response", "source", "model", "provider",
            "fallback_used", "fallback_trigger", "fallback_reason",
            "fallback_contract_version", "correlation_id",
        }
        assert required.issubset(result.keys()), f"missing: {required - result.keys()}"


class TestChatWithFallback:
    def test_fallback_on_connection_error(self):
        result = _make_fallback()
        assert result["fallback_used"] is True
        assert result["model"] == "fallback"
        assert result["provider"] == "static"
        assert "response" in result

    def test_fallback_includes_reason(self):
        result = _make_fallback()
        assert "fallback_reason" in result
        assert len(result["fallback_reason"]) > 0

    def test_fallback_preserves_correlation_id(self):
        result = _make_fallback(correlation_id="test-corr-123")
        assert result["correlation_id"] == "test-corr-123"

    def test_custom_fallback_message(self):
        result = _make_fallback(fallback_message="Service temporarily offline.")
        assert result["response"] == "Service temporarily offline."

    def test_default_fallback_message(self):
        result = _make_fallback()
        assert "unavailable" in result["response"].lower() or "try again" in result["response"].lower()

    def test_fallback_response_is_dict(self):
        result = _make_fallback()
        assert isinstance(result, dict)

    def test_all_chat_params_accepted(self):
        client = RouterClient(base_url="http://127.0.0.1:19999", timeout=0.5)
        result = run(client.chat_with_fallback(
            messages=[{"role": "user", "content": "test"}],
            model="test-model",
            task_type="vision",
            correlation_id="sig-test",
        ))
        assert isinstance(result, dict)
        assert result.get("correlation_id") == "sig-test"
        run(client.close())


class TestRouterClientErrorStructure:
    def test_error_has_code_and_message(self):
        err = RouterClientError("TIMEOUT", "Request timed out")
        assert err.code == "TIMEOUT"
        assert err.message == "Request timed out"

    def test_error_has_details(self):
        err = RouterClientError("UNAVAILABLE", "Down", {"port": 7010})
        assert err.details["port"] == 7010

    def test_error_str_includes_code(self):
        err = RouterClientError("CHAT_FAILED", "Bad response")
        assert "CHAT_FAILED" in str(err)


class TestFallbackTriggerConstants:
    def test_triggers_frozenset(self):
        assert isinstance(FALLBACK_TRIGGERS, frozenset)

    def test_known_triggers(self):
        assert "router_unavailable" in FALLBACK_TRIGGERS
        assert "router_error" in FALLBACK_TRIGGERS
        assert "unexpected_error" in FALLBACK_TRIGGERS
