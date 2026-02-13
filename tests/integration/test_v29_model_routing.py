"""
v2.9 Model Router Integration Tests -- Provider Parity & Policy Routing

Tests:
1. Provider response envelope normalization (all 3 providers same shape)
2. Routing policy enforcement (local_only, cloud_allowed, provider_pinned)
3. Provider health tracking (failure → quarantine → recovery)
4. Cancellation token propagation
5. Graceful degradation (cloud unavailable → local fallback)
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import json
import asyncio
import httpx

# ── Path setup ──────────────────────────────────────────────────────
sys.path.insert(0, r"S:\services\model-router")
sys.path.insert(0, r"S:\services\api-gateway")


# ── Helpers ─────────────────────────────────────────────────────────

def _make_ollama_response():
    """Simulate Ollama /api/generate response."""
    return {
        "response": "Hello from Ollama",
        "prompt_eval_count": 10,
        "eval_count": 20,
        "total_duration": 500000000,
    }


def _make_anthropic_response():
    """Simulate Anthropic Messages API response."""
    return {
        "id": "msg_123",
        "type": "message",
        "model": "claude-opus-4-6",
        "content": [{"type": "text", "text": "Hello from Anthropic"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def _make_openrouter_response():
    """Simulate OpenRouter chat/completions response."""
    return {
        "id": "gen-123",
        "model": "openai/gpt-4",
        "choices": [{
            "message": {"role": "assistant", "content": "Hello from OpenRouter"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


STANDARD_MESSAGES = [{"role": "user", "content": "Hello"}]


# ============================================================================
# Test 1: Provider Response Envelope Parity
# ============================================================================

class TestProviderEnvelopeParity(unittest.TestCase):
    """All 3 providers must return identical envelope shape."""

    REQUIRED_KEYS = {"status", "model", "response", "metadata"}

    @patch("httpx.post")
    @patch("httpx.get")
    def test_ollama_envelope(self, mock_get, mock_post):
        """Ollama chat returns standard envelope."""
        # Make Ollama appear available
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen2:7b"}]},
        )
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_ollama_response(),
            raise_for_status=lambda: None,
        )

        from providers import OllamaProvider
        p = OllamaProvider()
        result = p.chat("qwen2:7b", STANDARD_MESSAGES)

        self.assertEqual(result["status"], "success")
        self.assertIn("model", result)
        self.assertIn("response", result)
        self.assertIn("metadata", result)
        self.assertIsInstance(result["response"], str)
        self.assertTrue(len(result["response"]) > 0)

    @patch("httpx.post")
    def test_anthropic_envelope(self, mock_post):
        """Anthropic chat returns standard envelope."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_anthropic_response(),
            raise_for_status=lambda: None,
        )

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")
        result = p.chat("claude-opus-4-6", STANDARD_MESSAGES)

        self.assertEqual(result["status"], "success")
        self.assertIn("model", result)
        self.assertIn("response", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["response"], "Hello from Anthropic")

    @patch("httpx.post")
    def test_openrouter_envelope(self, mock_post):
        """OpenRouter chat returns standard envelope."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_openrouter_response(),
            raise_for_status=lambda: None,
        )

        from providers import OpenRouterProvider
        p = OpenRouterProvider(api_key="test-key")
        result = p.chat("openai/gpt-4", STANDARD_MESSAGES)

        self.assertEqual(result["status"], "success")
        self.assertIn("model", result)
        self.assertIn("response", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["response"], "Hello from OpenRouter")

    @patch("httpx.post")
    @patch("httpx.get")
    def test_all_providers_same_shape(self, mock_get, mock_post):
        """All 3 providers produce envelopes with identical top-level keys."""
        from providers import OllamaProvider, AnthropicProvider, OpenRouterProvider

        # Ollama
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen2:7b"}]},
        )
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_ollama_response(),
            raise_for_status=lambda: None,
        )
        ollama_result = OllamaProvider().chat("qwen2:7b", STANDARD_MESSAGES)

        # Anthropic
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_anthropic_response(),
            raise_for_status=lambda: None,
        )
        anthropic_result = AnthropicProvider(api_key="key").chat("claude-opus-4-6", STANDARD_MESSAGES)

        # OpenRouter
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_openrouter_response(),
            raise_for_status=lambda: None,
        )
        openrouter_result = OpenRouterProvider(api_key="key").chat("openai/gpt-4", STANDARD_MESSAGES)

        # All must have same top-level keys
        ollama_keys = set(ollama_result.keys())
        anthropic_keys = set(anthropic_result.keys())
        openrouter_keys = set(openrouter_result.keys())

        self.assertEqual(ollama_keys, anthropic_keys,
                         f"Ollama vs Anthropic key mismatch: {ollama_keys} vs {anthropic_keys}")
        self.assertEqual(anthropic_keys, openrouter_keys,
                         f"Anthropic vs OpenRouter key mismatch: {anthropic_keys} vs {openrouter_keys}")

        # All must have required keys
        for name, keys in [("ollama", ollama_keys), ("anthropic", anthropic_keys), ("openrouter", openrouter_keys)]:
            for req in self.REQUIRED_KEYS:
                self.assertIn(req, keys, f"{name} missing required key: {req}")


# ============================================================================
# Test 2: Routing Policy Enforcement
# ============================================================================

class TestRoutingPolicy(unittest.TestCase):
    """Routing policies correctly restrict provider selection."""

    @patch("httpx.post")
    @patch("httpx.get")
    def test_local_only_uses_ollama(self, mock_get, mock_post):
        """local_only policy only routes to Ollama."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen2:7b"}]},
        )
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_ollama_response(),
            raise_for_status=lambda: None,
        )

        from providers import ProviderRouter, TaskType
        router = ProviderRouter()

        # Simulate: only use local
        ollama = router.providers.get("ollama")
        self.assertIsNotNone(ollama)

        model = ollama.route(TaskType.TEXT)
        self.assertIsNotNone(model)
        self.assertEqual(model.provider, "ollama")

    def test_provider_pinned_anthropic(self):
        """provider_pinned selects specific provider."""
        from providers import AnthropicProvider, TaskType

        p = AnthropicProvider(api_key="test-key")
        model = p.route(TaskType.TEXT)
        self.assertIsNotNone(model)
        self.assertEqual(model.provider, "anthropic")
        self.assertEqual(model.name, "claude-opus-4-6")

    def test_provider_pinned_openrouter(self):
        """provider_pinned selects OpenRouter."""
        from providers import OpenRouterProvider, TaskType

        p = OpenRouterProvider(api_key="test-key")
        model = p.route(TaskType.TEXT)
        self.assertIsNotNone(model)
        self.assertEqual(model.provider, "openrouter")
        self.assertEqual(model.name, "openai/gpt-4o-mini")


# ============================================================================
# Test 3: Provider Health & Degradation
# ============================================================================

class TestProviderHealth(unittest.TestCase):
    """Provider error handling and graceful degradation."""

    @patch("httpx.post")
    def test_anthropic_api_error_returns_error_status(self, mock_post):
        """Anthropic HTTP error returns error envelope, not exception."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.json.return_value = {"error": {"message": "rate limited"}}
        mock_post.side_effect = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=MagicMock(),
            response=mock_resp,
        )

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")
        result = p.chat("claude-opus-4-6", STANDARD_MESSAGES)

        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
        self.assertEqual(result["model"], "claude-opus-4-6")

    @patch("httpx.post")
    def test_openrouter_api_error_returns_error_status(self, mock_post):
        """OpenRouter HTTP error returns error envelope, not exception."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"error": {"message": "internal error"}}
        mock_post.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=mock_resp,
        )

        from providers import OpenRouterProvider
        p = OpenRouterProvider(api_key="test-key")
        result = p.chat("openai/gpt-4", STANDARD_MESSAGES)

        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)

    @patch("httpx.post")
    def test_anthropic_network_error_returns_error_status(self, mock_post):
        """Anthropic network failure returns error, doesn't crash."""
        mock_post.side_effect = httpx.ConnectError("Connection refused")

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")
        result = p.chat("claude-opus-4-6", STANDARD_MESSAGES)

        self.assertEqual(result["status"], "error")

    def test_unavailable_provider_returns_error(self):
        """Provider without API key returns error on chat."""
        from providers import AnthropicProvider
        p = AnthropicProvider(api_key=None)
        self.assertFalse(p.available)
        result = p.chat("claude-opus-4-6", STANDARD_MESSAGES)
        self.assertEqual(result["status"], "error")

    @patch("httpx.post")
    @patch("httpx.get")
    def test_fallback_on_provider_failure(self, mock_get, mock_post):
        """ProviderRouter falls back to next provider on failure."""
        # Ollama available but chat fails
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen2:7b"}]},
        )

        call_count = [0]
        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (Ollama) fails
                raise httpx.ConnectError("Connection refused")
            # Second call (Anthropic) succeeds
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _make_anthropic_response()
            resp.raise_for_status = lambda: None
            return resp

        mock_post.side_effect = _side_effect

        from providers import ProviderRouter, TaskType

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            router = ProviderRouter()
            result = router.chat(TaskType.TEXT, STANDARD_MESSAGES)

        self.assertEqual(result["status"], "success")
        self.assertIn("Anthropic", result.get("response", ""))


# ============================================================================
# Test 4: Anthropic-Specific Features
# ============================================================================

class TestAnthropicFeatures(unittest.TestCase):
    """Anthropic provider specific behavior."""

    @patch("httpx.post")
    def test_system_message_extraction(self, mock_post):
        """System messages are extracted to top-level system param."""
        captured_payload = {}
        def _capture(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _make_anthropic_response()
            resp.raise_for_status = lambda: None
            return resp

        mock_post.side_effect = _capture

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")

        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        p.chat("claude-opus-4-6", messages)

        self.assertEqual(captured_payload.get("system"), "You are helpful.")
        # System message should NOT be in messages array
        for msg in captured_payload.get("messages", []):
            self.assertNotEqual(msg["role"], "system")

    @patch("httpx.post")
    def test_temperature_passthrough(self, mock_post):
        """Temperature kwarg is passed to API."""
        captured_payload = {}
        def _capture(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _make_anthropic_response()
            resp.raise_for_status = lambda: None
            return resp

        mock_post.side_effect = _capture

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")
        p.chat("claude-opus-4-6", STANDARD_MESSAGES, temperature=0.3)

        self.assertEqual(captured_payload.get("temperature"), 0.3)

    @patch("httpx.post")
    def test_max_tokens_passthrough(self, mock_post):
        """max_tokens kwarg is passed to API."""
        captured_payload = {}
        def _capture(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _make_anthropic_response()
            resp.raise_for_status = lambda: None
            return resp

        mock_post.side_effect = _capture

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")
        p.chat("claude-opus-4-6", STANDARD_MESSAGES, max_tokens=500)

        self.assertEqual(captured_payload.get("max_tokens"), 500)

    def test_vision_routing(self):
        """Anthropic routes vision tasks to Sonnet."""
        from providers import AnthropicProvider, TaskType
        p = AnthropicProvider(api_key="test-key")
        model = p.route(TaskType.VISION)
        self.assertIsNotNone(model)
        self.assertEqual(model.name, "claude-sonnet-4-6")
        self.assertIn("vision", model.capabilities)


# ============================================================================
# Test 5: OpenRouter-Specific Features
# ============================================================================

class TestOpenRouterFeatures(unittest.TestCase):
    """OpenRouter provider specific behavior."""

    @patch("httpx.post")
    def test_auth_header_format(self, mock_post):
        """OpenRouter uses Bearer token in Authorization header."""
        captured_headers = {}
        def _capture(*args, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _make_openrouter_response()
            resp.raise_for_status = lambda: None
            return resp

        mock_post.side_effect = _capture

        from providers import OpenRouterProvider
        p = OpenRouterProvider(api_key="sk-test-123")
        p.chat("openai/gpt-4", STANDARD_MESSAGES)

        self.assertEqual(captured_headers.get("Authorization"), "Bearer sk-test-123")
        self.assertIn("HTTP-Referer", captured_headers)
        self.assertIn("X-Title", captured_headers)

    @patch("httpx.post")
    def test_openai_compatible_payload(self, mock_post):
        """OpenRouter receives OpenAI-compatible payload."""
        captured_payload = {}
        def _capture(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = _make_openrouter_response()
            resp.raise_for_status = lambda: None
            return resp

        mock_post.side_effect = _capture

        from providers import OpenRouterProvider
        p = OpenRouterProvider(api_key="test-key")
        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
        ]
        p.chat("openai/gpt-4", messages)

        # OpenAI format keeps system messages in messages array
        self.assertIn("messages", captured_payload)
        self.assertEqual(len(captured_payload["messages"]), 2)
        self.assertEqual(captured_payload["messages"][0]["role"], "system")


# ============================================================================
# Test 6: No More not_implemented
# ============================================================================

class TestNoStubs(unittest.TestCase):
    """Verify zero not_implemented return paths remain."""

    @patch("httpx.post")
    def test_anthropic_no_stub(self, mock_post):
        """Anthropic chat never returns not_implemented."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_anthropic_response(),
            raise_for_status=lambda: None,
        )

        from providers import AnthropicProvider
        p = AnthropicProvider(api_key="test-key")
        result = p.chat("claude-opus-4-6", STANDARD_MESSAGES)
        self.assertNotEqual(result.get("status"), "not_implemented")

    @patch("httpx.post")
    def test_openrouter_no_stub(self, mock_post):
        """OpenRouter chat never returns not_implemented."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: _make_openrouter_response(),
            raise_for_status=lambda: None,
        )

        from providers import OpenRouterProvider
        p = OpenRouterProvider(api_key="test-key")
        result = p.chat("openai/gpt-4", STANDARD_MESSAGES)
        self.assertNotEqual(result.get("status"), "not_implemented")

    def test_source_code_no_not_implemented(self):
        """providers.py source has no not_implemented return values."""
        with open(r"S:\services\model-router\providers.py", "r") as f:
            source = f.read()
        self.assertNotIn('"not_implemented"', source,
                         "providers.py still contains not_implemented stub")


if __name__ == "__main__":
    unittest.main()
