"""
v2.10 Integration Tests -- Perception VLM Real Inference Path

Tests the replacement of the perception VLM stub with real
model-router calls. Validates:
  1. run_vlm_inference builds correct vision message format
  2. Graceful fallback on model-router failure
  3. SceneAnalysis contract preserved
  4. Ollama provider handles multimodal messages
  5. Anthropic provider converts to native vision format

Tests (15):
  VLM Inference (5):
    1. run_vlm_inference sends correct payload to model-router
    2. Graceful fallback on httpx timeout
    3. Graceful fallback on non-success response
    4. Empty frames list still calls model-router
    5. Context string is included in analysis prompt

  Provider Vision Support (6):
    6. OllamaProvider.chat extracts images from multimodal content
    7. OllamaProvider.chat handles plain text messages unchanged
    8. AnthropicProvider.chat converts image_url to native format
    9. AnthropicProvider.chat handles system messages with vision
    10. OpenRouterProvider.chat passes multimodal content through
    11. Provider routing selects vision-capable model for VISION task

  SceneAnalysis Contract (4):
    12. SceneAnalysis action_requires_confirmation always True
    13. SceneAnalysis accepts entities from real inference
    14. SceneAnalysis confidence between 0 and 1
    15. SceneAnalysis model_used populated from real response
"""

import sys
import asyncio
import base64
import json
import time
import importlib.util
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# Use importlib to load perception/main.py to avoid collision with model-router/main.py
def _load_perception_main():
    """Load perception main.py as a named module."""
    mod_name = "perception_main"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    # Ensure perception dir is on path for its own relative imports
    if r"S:\services\perception" not in sys.path:
        sys.path.insert(0, r"S:\services\perception")
    spec = importlib.util.spec_from_file_location(mod_name, r"S:\services\perception\main.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod

sys.path.insert(0, r"S:\services\model-router")


# ===========================================================================
# VLM Inference tests
# ===========================================================================

class TestVLMInference:

    @pytest.mark.asyncio
    async def test_vlm_sends_correct_payload(self):
        """run_vlm_inference builds OpenAI vision format messages."""
        pm = _load_perception_main()
        run_vlm_inference = pm.run_vlm_inference
        MODEL_ROUTER_URL = pm.MODEL_ROUTER_URL

        fake_frame = {
            "data_b64": base64.b64encode(b"fake-image-data").decode(),
            "mime_type": "image/png",
        }

        captured = {}

        class FakeResponse:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {
                    "status": "success",
                    "model": "llava:7b",
                    "response": "A test scene with objects.",
                }

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, url, json=None, **kw):
                captured["url"] = url
                captured["payload"] = json
                return FakeResponse()

        with patch("perception_main.httpx.AsyncClient", return_value=FakeClient()):
            result = await run_vlm_inference([fake_frame], "test context", 2000)

        assert captured["url"] == f"{MODEL_ROUTER_URL}/chat"
        payload = captured["payload"]
        assert payload["task_type"] == "vision"
        msgs = payload["messages"]
        assert len(msgs) == 1
        content = msgs[0]["content"]
        # Should have text + image_url parts
        types = [p["type"] for p in content]
        assert "text" in types
        assert "image_url" in types

    @pytest.mark.asyncio
    async def test_vlm_fallback_on_timeout(self):
        """Graceful degradation when model-router times out."""
        import httpx as _httpx

        class TimeoutClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, *a, **kw):
                raise _httpx.ReadTimeout("timeout")

        with patch("perception_main.httpx.AsyncClient", return_value=TimeoutClient()):
            run_vlm_inference = _load_perception_main().run_vlm_inference
            result = await run_vlm_inference([], "", 1000)

        assert result["model_used"] == "fallback/error"
        assert result["overall_confidence"] == 0.0
        assert "failed" in result["summary"].lower() or "error" in result["summary"].lower()

    @pytest.mark.asyncio
    async def test_vlm_fallback_on_non_success(self):
        """Fallback when model-router returns status != success."""
        class ErrorResponse:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"status": "error", "error": "model not found"}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, *a, **kw): return ErrorResponse()

        with patch("perception_main.httpx.AsyncClient", return_value=FakeClient()):
            run_vlm_inference = _load_perception_main().run_vlm_inference
            result = await run_vlm_inference([], "", 2000)

        assert result["model_used"] == "fallback/error"

    @pytest.mark.asyncio
    async def test_vlm_empty_frames(self):
        """Empty frames list still produces valid call."""
        class OkResponse:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"status": "success", "model": "test", "response": "Empty scene."}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, url, json=None, **kw):
                # Only text part, no image_url
                content = json["messages"][0]["content"]
                assert all(p["type"] == "text" for p in content)
                return OkResponse()

        with patch("perception_main.httpx.AsyncClient", return_value=FakeClient()):
            run_vlm_inference = _load_perception_main().run_vlm_inference
            result = await run_vlm_inference([], "", 2000)

        assert result["summary"] == "Empty scene."
        assert result["model_used"] == "test"

    @pytest.mark.asyncio
    async def test_vlm_includes_context(self):
        """Context string appears in the analysis prompt."""
        captured = {}

        class OkResponse:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"status": "success", "model": "m", "response": "ok"}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, url, json=None, **kw):
                captured["payload"] = json
                return OkResponse()

        with patch("perception_main.httpx.AsyncClient", return_value=FakeClient()):
            run_vlm_inference = _load_perception_main().run_vlm_inference
            await run_vlm_inference([], "user is cooking dinner", 2000)

        text_part = captured["payload"]["messages"][0]["content"][0]
        assert "user is cooking dinner" in text_part["text"]


# ===========================================================================
# Provider Vision Support tests
# ===========================================================================

class TestProviderVisionSupport:

    def test_ollama_extracts_images_from_multimodal(self):
        """OllamaProvider.chat extracts base64 images from content list."""
        from providers import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.name = "ollama"
        provider.endpoint = "http://127.0.0.1:11434"
        provider.api_key = None
        provider.available = True
        provider.default_model = "llava:7b"

        b64_data = base64.b64encode(b"test").decode()
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe this"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}},
            ],
        }]

        captured = {}
        original_post = None

        def mock_post(url, json=None, **kw):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"response": "A test image"}
            return resp

        with patch("providers.httpx.post", side_effect=mock_post):
            result = provider.chat("llava:7b", messages)

        assert "images" in captured["payload"]
        assert captured["payload"]["images"] == [b64_data]
        assert "Describe this" in captured["payload"]["prompt"]

    def test_ollama_plain_text_unchanged(self):
        """OllamaProvider.chat handles plain text messages normally."""
        from providers import OllamaProvider
        provider = OllamaProvider.__new__(OllamaProvider)
        provider.name = "ollama"
        provider.endpoint = "http://127.0.0.1:11434"
        provider.api_key = None
        provider.available = True
        provider.default_model = "qwen2.5:7b"

        messages = [{"role": "user", "content": "Hello world"}]

        captured = {}

        def mock_post(url, json=None, **kw):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"response": "Hi there"}
            return resp

        with patch("providers.httpx.post", side_effect=mock_post):
            provider.chat("qwen2.5:7b", messages)

        assert "images" not in captured["payload"]
        assert "Hello world" in captured["payload"]["prompt"]

    def test_anthropic_converts_to_native_vision(self):
        """AnthropicProvider converts image_url to Anthropic image format."""
        from providers import AnthropicProvider
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.name = "anthropic"
        provider.endpoint = "https://api.anthropic.com"
        provider.api_key = "test-key"
        provider.available = True

        b64_data = base64.b64encode(b"image-bytes").decode()
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_data}"}},
            ],
        }]

        captured = {}

        def mock_post(url, json=None, **kw):
            captured["payload"] = json
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "content": [{"type": "text", "text": "It's a test"}],
                "usage": {},
            }
            return resp

        with patch("providers.httpx.post", side_effect=mock_post):
            result = provider.chat("claude-sonnet-4-6", messages)

        api_msg = captured["payload"]["messages"][0]
        assert api_msg["role"] == "user"
        # Should have Anthropic-native image format
        content = api_msg["content"]
        image_part = [p for p in content if p.get("type") == "image"][0]
        assert image_part["source"]["type"] == "base64"
        assert image_part["source"]["media_type"] == "image/jpeg"
        assert image_part["source"]["data"] == b64_data

    def test_anthropic_system_with_vision(self):
        """System messages handled correctly alongside vision content."""
        from providers import AnthropicProvider
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.name = "anthropic"
        provider.endpoint = "https://api.anthropic.com"
        provider.api_key = "test-key"
        provider.available = True

        messages = [
            {"role": "system", "content": "You are an analyst."},
            {"role": "user", "content": [{"type": "text", "text": "Analyze"}]},
        ]

        captured = {}

        def mock_post(url, json=None, **kw):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"content": [{"type": "text", "text": "ok"}], "usage": {}}
            return resp

        with patch("providers.httpx.post", side_effect=mock_post):
            provider.chat("claude-sonnet-4-6", messages)

        assert captured["payload"]["system"] == "You are an analyst."
        assert len(captured["payload"]["messages"]) == 1

    def test_openrouter_passes_multimodal(self):
        """OpenRouter passes multimodal content through (OpenAI-compatible)."""
        from providers import OpenRouterProvider
        provider = OpenRouterProvider.__new__(OpenRouterProvider)
        provider.name = "openrouter"
        provider.endpoint = "https://openrouter.ai/api/v1"
        provider.api_key = "test-key"
        provider.available = True

        b64 = base64.b64encode(b"img").decode()
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "What?"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }]

        captured = {}

        def mock_post(url, json=None, **kw):
            captured["payload"] = json
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "choices": [{"message": {"content": "An image"}, "finish_reason": "stop"}],
                "usage": {},
            }
            return resp

        with patch("providers.httpx.post", side_effect=mock_post):
            result = provider.chat("openai/gpt-4o", messages)

        # Content should be passed through as-is (list format)
        api_content = captured["payload"]["messages"][0]["content"]
        assert isinstance(api_content, list)
        assert len(api_content) == 2

    def test_vision_routing_selects_capable_model(self):
        """Provider routing returns vision-capable model for VISION task."""
        from providers import TaskType, OllamaProvider, AnthropicProvider

        # Anthropic always supports vision
        provider = AnthropicProvider.__new__(AnthropicProvider)
        provider.name = "anthropic"
        provider.endpoint = "https://api.anthropic.com"
        provider.api_key = "test-key"
        provider.available = True

        model = provider.route(TaskType.VISION)
        assert model is not None
        assert "vision" in model.capabilities


# ===========================================================================
# SceneAnalysis Contract tests
# ===========================================================================

class TestSceneAnalysisContract:

    def test_confirmation_always_true(self):
        """action_requires_confirmation cannot be set to False."""
        pm = _load_perception_main()
        SceneAnalysis, TriggerType = pm.SceneAnalysis, pm.TriggerType
        scene = SceneAnalysis(
            scene_id="test",
            timestamp=time.time(),
            trigger=TriggerType.USER_COMMAND,
            summary="test scene",
            overall_confidence=0.5,
            action_requires_confirmation=False,  # attempt override
            inference_ms=10.0,
        )
        assert scene.action_requires_confirmation is True

    def test_scene_accepts_real_entities(self):
        """SceneAnalysis with real entity data from model output."""
        pm = _load_perception_main()
        SceneAnalysis, TriggerType, Entity = pm.SceneAnalysis, pm.TriggerType, pm.Entity
        scene = SceneAnalysis(
            scene_id="real-test",
            timestamp=time.time(),
            trigger=TriggerType.USER_COMMAND,
            summary="Kitchen with person cooking",
            entities=[
                Entity(label="person", confidence=0.92),
                Entity(label="stove", confidence=0.87, attributes={"state": "on"}),
            ],
            overall_confidence=0.89,
            inference_ms=450.0,
            model_used="llava:7b",
        )
        assert len(scene.entities) == 2
        assert scene.entities[0].confidence == 0.92
        assert scene.model_used == "llava:7b"

    def test_scene_confidence_bounds(self):
        """Confidence must be between 0 and 1."""
        pm = _load_perception_main()
        SceneAnalysis, TriggerType = pm.SceneAnalysis, pm.TriggerType
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            SceneAnalysis(
                scene_id="bad",
                timestamp=time.time(),
                trigger=TriggerType.MOTION,
                summary="test",
                overall_confidence=1.5,
                inference_ms=10.0,
            )

    def test_scene_model_used_from_response(self):
        """model_used populated from real inference response."""
        pm = _load_perception_main()
        SceneAnalysis, TriggerType = pm.SceneAnalysis, pm.TriggerType
        scene = SceneAnalysis(
            scene_id="m",
            timestamp=time.time(),
            trigger=TriggerType.SCHEDULED,
            summary="Empty room",
            overall_confidence=0.5,
            inference_ms=200.0,
            model_used="claude-sonnet-4-6",
        )
        assert scene.model_used == "claude-sonnet-4-6"
        assert scene.model_used != "stub/none"
