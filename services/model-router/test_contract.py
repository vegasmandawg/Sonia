"""
Model Router Contract Tests

Validates that Model Router meets the BOOT_CONTRACT.md requirements:
- Provider routing working
- Ollama integration functional
- End-to-end /chat working
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from providers import (
    TaskType, ModelInfo, OllamaProvider, ProviderRouter,
    AnthropicProvider, OpenRouterProvider
)


class TestModelInfo:
    """Test ModelInfo class."""
    
    def test_model_info_creation(self):
        """Create model info."""
        model = ModelInfo(
            name="test-model",
            provider="test",
            capabilities=["text", "vision"]
        )
        
        assert model.name == "test-model"
        assert model.provider == "test"
        assert model.capabilities == ["text", "vision"]
    
    def test_model_info_to_dict(self):
        """Convert model info to dict."""
        model = ModelInfo(
            name="test",
            provider="ollama",
            capabilities=["text"],
            config={"temp": 0.7}
        )
        
        data = model.to_dict()
        
        assert data["name"] == "test"
        assert data["provider"] == "ollama"
        assert data["config"]["temp"] == 0.7


class TestOllamaProvider:
    """Test Ollama provider."""
    
    @patch('providers.httpx.get')
    def test_ollama_availability_check(self, mock_get):
        """Check Ollama availability."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response
        
        provider = OllamaProvider()
        
        assert provider.available is True
        assert provider.name == "ollama"
    
    @patch('providers.httpx.get')
    def test_ollama_availability_check_fail(self, mock_get):
        """Check Ollama unavailability."""
        mock_get.side_effect = Exception("Connection refused")
        
        provider = OllamaProvider()
        
        assert provider.available is False
    
    @patch('providers.httpx.get')
    def test_ollama_get_models(self, mock_get):
        """Get models from Ollama."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "qwen2:7b"},
                {"name": "qwen2-vl:7b"},
                {"name": "bge-m3"}
            ]
        }
        mock_get.return_value = mock_response
        
        provider = OllamaProvider()
        provider.available = True
        
        models = provider.get_models()
        
        assert len(models) == 3
        assert models[0].name == "qwen2:7b"
        assert "text" in models[0].capabilities
    
    @patch('providers.httpx.post')
    def test_ollama_chat(self, mock_post):
        """Send chat request to Ollama."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "response": "Hello!",
            "prompt_eval_count": 10,
            "eval_count": 5,
            "total_duration": 1000000000
        }
        mock_post.return_value = mock_response
        
        provider = OllamaProvider()
        provider.available = True
        
        messages = [{"role": "user", "content": "Hello"}]
        result = provider.chat("qwen2:7b", messages)
        
        assert result["status"] == "success"
        assert "Hello!" in result["response"]
    
    @patch('providers.httpx.post')
    def test_ollama_chat_error(self, mock_post):
        """Chat error handling."""
        mock_post.side_effect = Exception("Connection error")
        
        provider = OllamaProvider()
        provider.available = True
        
        messages = [{"role": "user", "content": "Hello"}]
        result = provider.chat("qwen2:7b", messages)
        
        assert result["status"] == "error"
        assert "Connection error" in result["error"]


class TestProviderRouter:
    """Test provider router."""
    
    @patch('providers.OllamaProvider')
    def test_router_initialization(self, mock_ollama):
        """Initialize provider router."""
        mock_provider = Mock()
        mock_provider.available = True
        mock_ollama.return_value = mock_provider
        
        router = ProviderRouter()
        
        assert "ollama" in router.providers
    
    @patch('providers.httpx.get')
    def test_router_route_text(self, mock_get):
        """Route text task."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "qwen2:7b"}]
        }
        mock_get.return_value = mock_response
        
        router = ProviderRouter()
        model = router.route(TaskType.TEXT)
        
        assert model is not None
        assert "text" in model.capabilities
    
    @patch('providers.httpx.get')
    def test_router_route_vision(self, mock_get):
        """Route vision task."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "qwen2:7b"},
                {"name": "qwen2-vl:7b"}
            ]
        }
        mock_get.return_value = mock_response
        
        router = ProviderRouter()
        model = router.route(TaskType.VISION)
        
        assert model is not None
        assert "vision" in model.capabilities
    
    @patch('providers.httpx.get')
    def test_router_get_all_models(self, mock_get):
        """Get all models."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "qwen2:7b"},
                {"name": "qwen2-vl:7b"}
            ]
        }
        mock_get.return_value = mock_response
        
        router = ProviderRouter()
        models = router.get_all_models()
        
        assert "ollama" in models
        assert len(models["ollama"]) > 0


class TestAnthropicProvider:
    """Test Anthropic provider."""
    
    def test_anthropic_availability_without_key(self):
        """Anthropic unavailable without API key."""
        with patch.dict('os.environ', {}, clear=True):
            provider = AnthropicProvider()
            
            assert provider.available is False
    
    def test_anthropic_availability_with_key(self):
        """Anthropic available with API key."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            provider = AnthropicProvider()
            
            assert provider.available is True
    
    def test_anthropic_get_models(self):
        """Get Claude models."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            provider = AnthropicProvider()
            
            models = provider.get_models()
            
            assert len(models) > 0
            assert any("claude" in m.name for m in models)


class TestOpenRouterProvider:
    """Test OpenRouter provider."""
    
    def test_openrouter_availability_without_key(self):
        """OpenRouter unavailable without API key."""
        with patch.dict('os.environ', {}, clear=True):
            provider = OpenRouterProvider()
            
            assert provider.available is False
    
    def test_openrouter_availability_with_key(self):
        """OpenRouter available with API key."""
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-key'}):
            provider = OpenRouterProvider()
            
            assert provider.available is True


class TestIntegration:
    """Integration tests."""
    
    @patch('providers.httpx.get')
    @patch('providers.httpx.post')
    def test_end_to_end_chat(self, mock_post, mock_get):
        """End-to-end chat workflow."""
        # Setup Ollama availability
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {
            "models": [{"name": "qwen2:7b"}]
        }
        mock_get.return_value = mock_get_response
        
        # Setup chat response
        mock_post_response = Mock()
        mock_post_response.json.return_value = {
            "response": "Test response",
            "prompt_eval_count": 10,
            "eval_count": 5,
            "total_duration": 1000000000
        }
        mock_post.return_value = mock_post_response
        
        # Test workflow
        router = ProviderRouter()
        
        # 1. Route text task
        model = router.route(TaskType.TEXT)
        assert model is not None
        
        # 2. Send chat
        messages = [{"role": "user", "content": "Hello"}]
        result = router.chat(TaskType.TEXT, messages)
        
        assert result["status"] == "success"
        assert "Test response" in result["response"]


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
