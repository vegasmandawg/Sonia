"""
Model Router Provider Abstraction

Provides unified interface for multiple LLM providers.
Currently implements: Ollama (local), with support for Anthropic and OpenRouter.
"""

import httpx
import json
import logging
import os
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
from enum import Enum

logger = logging.getLogger('model-router.providers')


class TaskType(Enum):
    """Task types for model routing."""
    TEXT = "text"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    RERANKER = "reranker"


class ModelInfo:
    """Information about a model."""
    
    def __init__(self, name: str, provider: str, capabilities: List[str], 
                 config: Optional[Dict] = None):
        self.name = name
        self.provider = provider
        self.capabilities = capabilities
        self.config = config or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "config": self.config
        }


class Provider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, name: str, endpoint: str, api_key: Optional[str] = None):
        """Initialize provider."""
        self.name = name
        self.endpoint = endpoint
        self.api_key = api_key
        self.available = False
        self._check_availability()
    
    @abstractmethod
    def _check_availability(self):
        """Check if provider is available."""
        pass
    
    @abstractmethod
    def get_models(self) -> List[ModelInfo]:
        """Get available models."""
        pass
    
    @abstractmethod
    def route(self, task_type: TaskType) -> Optional[ModelInfo]:
        """Route to appropriate model for task."""
        pass
    
    @abstractmethod
    def chat(self, model: str, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Send chat request to provider."""
        pass


class OllamaProvider(Provider):
    """Local Ollama provider."""
    
    def __init__(self, endpoint: Optional[str] = None):
        """Initialize Ollama provider."""
        endpoint = endpoint or os.getenv("OLLAMA_ENDPOINT", "http://127.0.0.1:11434")
        super().__init__("ollama", endpoint, api_key=None)
        self.default_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    
    def _check_availability(self):
        """Check if Ollama is running."""
        try:
            response = httpx.get(f"{self.endpoint}/api/tags", timeout=2)
            self.available = response.status_code == 200
            if self.available:
                logger.info("Ollama provider available")
            else:
                logger.warning("Ollama provider returned non-200 status")
        except Exception as e:
            logger.warning(f"Ollama not available: {e}")
            self.available = False
    
    def get_models(self) -> List[ModelInfo]:
        """Get available models from Ollama."""
        if not self.available:
            return []
        
        try:
            response = httpx.get(f"{self.endpoint}/api/tags", timeout=5)
            response.raise_for_status()
            
            data = response.json()
            models = []
            
            for model_data in data.get("models", []):
                model_name = model_data.get("name", "unknown")
                
                # Determine capabilities based on model name
                capabilities = ["text"]
                if "vision" in model_name.lower() or "vl" in model_name.lower():
                    capabilities.append("vision")
                if "embed" in model_name.lower():
                    capabilities.append("embeddings")
                
                model = ModelInfo(
                    name=model_name,
                    provider="ollama",
                    capabilities=capabilities,
                    config={
                        "context_length": 2048,
                        "stop_tokens": ["<|im_end|>"]
                    }
                )
                models.append(model)
            
            return models
        
        except Exception as e:
            logger.error(f"Failed to get Ollama models: {e}")
            return []
    
    def route(self, task_type: TaskType) -> Optional[ModelInfo]:
        """Route to appropriate model for task."""
        if not self.available:
            return None
        
        models = self.get_models()
        if not models:
            return None
        
        # Route logic based on task type
        if task_type == TaskType.TEXT:
            # Return default text model
            for model in models:
                if self.default_model in model.name:
                    return model
            # Fallback to first available text model
            return next((m for m in models if "text" in m.capabilities), models[0])
        
        elif task_type == TaskType.VISION:
            # Find vision model
            return next((m for m in models if "vision" in m.capabilities), None)
        
        elif task_type == TaskType.EMBEDDINGS:
            # Find embeddings model
            return next((m for m in models if "embeddings" in m.capabilities), None)
        
        elif task_type == TaskType.RERANKER:
            # Find reranker model
            return next((m for m in models if "reranker" in m.capabilities), None)
        
        return None
    
    def chat(self, model: str, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Send chat request to Ollama."""
        if not self.available:
            return {
                "status": "error",
                "error": "Ollama provider not available"
            }
        
        try:
            # Ollama API format
            prompt = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                prompt += f"{role}: {content}\n"
            
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
            if "temperature" in kwargs:
                payload["options"] = payload.get("options", {})
                payload["options"]["temperature"] = kwargs["temperature"]
            
            response = httpx.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            return {
                "status": "success",
                "model": model,
                "response": data.get("response", ""),
                "metadata": {
                    "prompt_eval_count": data.get("prompt_eval_count"),
                    "eval_count": data.get("eval_count"),
                    "total_duration": data.get("total_duration")
                }
            }
        
        except Exception as e:
            logger.error(f"Ollama chat error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "model": model
            }


class AnthropicProvider(Provider):
    """Anthropic Claude provider (optional)."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Anthropic provider."""
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        super().__init__("anthropic", "https://api.anthropic.com", api_key)
    
    def _check_availability(self):
        """Check if API key is available."""
        self.available = bool(self.api_key)
        if self.available:
            logger.info("Anthropic provider configured")
        else:
            logger.debug("Anthropic provider not configured (no API key)")
    
    def get_models(self) -> List[ModelInfo]:
        """Get available Claude models."""
        if not self.available:
            return []

        return [
            ModelInfo("claude-opus-4-6", "anthropic", ["text", "vision"],
                      config={"context_length": 200000}),
            ModelInfo("claude-sonnet-4-6", "anthropic", ["text", "vision"],
                      config={"context_length": 200000}),
            ModelInfo("claude-haiku-4-5", "anthropic", ["text", "vision"],
                      config={"context_length": 200000}),
        ]
    
    def route(self, task_type: TaskType) -> Optional[ModelInfo]:
        """Route to appropriate Claude model."""
        if not self.available:
            return None
        if task_type not in (TaskType.TEXT, TaskType.VISION):
            return None

        # Default to Opus for text, Sonnet for vision (cost-effective)
        if task_type == TaskType.VISION:
            return ModelInfo("claude-sonnet-4-6", "anthropic", ["text", "vision"],
                             config={"context_length": 200000})
        return ModelInfo("claude-opus-4-6", "anthropic", ["text", "vision"],
                         config={"context_length": 200000})
    
    def chat(self, model: str, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Send chat request to Anthropic Messages API."""
        if not self.available:
            return {"status": "error", "error": "Anthropic provider not available"}

        try:
            # Build Anthropic Messages API payload
            # Extract system message if present; Anthropic uses a top-level system param
            system_text = ""
            api_messages = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    system_text = content
                else:
                    api_messages.append({"role": role, "content": content})

            # Ensure at least one user message
            if not api_messages:
                api_messages.append({"role": "user", "content": ""})

            payload = {
                "model": model,
                "messages": api_messages,
                "max_tokens": kwargs.get("max_tokens", 2048),
            }
            if system_text:
                payload["system"] = system_text
            if "temperature" in kwargs:
                payload["temperature"] = kwargs["temperature"]

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",  # Stable API version
                "content-type": "application/json",
            }

            response = httpx.post(
                f"{self.endpoint}/v1/messages",
                json=payload,
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            # Extract text from content blocks
            text_parts = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            usage = data.get("usage", {})

            return {
                "status": "success",
                "model": data.get("model", model),
                "response": "".join(text_parts),
                "metadata": {
                    "prompt_tokens": usage.get("input_tokens"),
                    "completion_tokens": usage.get("output_tokens"),
                    "stop_reason": data.get("stop_reason"),
                },
            }

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                error_body = str(e)
            logger.error(f"Anthropic API error ({e.response.status_code}): {error_body}")
            return {
                "status": "error",
                "error": f"Anthropic API error: {error_body}",
                "model": model,
            }
        except Exception as e:
            logger.error(f"Anthropic chat error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "model": model,
            }


class OpenRouterProvider(Provider):
    """OpenRouter provider (optional)."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenRouter provider."""
        api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        endpoint = os.getenv("OPENROUTER_ENDPOINT", "https://openrouter.ai/api/v1")
        super().__init__("openrouter", endpoint, api_key)
    
    def _check_availability(self):
        """Check if API key is available."""
        self.available = bool(self.api_key)
        if self.available:
            logger.info("OpenRouter provider configured")
        else:
            logger.debug("OpenRouter provider not configured (no API key)")
    
    def get_models(self) -> List[ModelInfo]:
        """Get available models from OpenRouter via API, with static fallback."""
        if not self.available:
            return []

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = httpx.get(
                f"{self.endpoint}/models",
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for m in data.get("data", []):
                model_id = m.get("id", "")
                caps = ["text"]
                arch = m.get("architecture", {})
                if arch.get("modality", "") == "multimodal" or "vision" in model_id.lower():
                    caps.append("vision")
                models.append(ModelInfo(model_id, "openrouter", caps))
            return models[:50]

        except Exception as e:
            logger.warning(f"OpenRouter model list fetch failed, using defaults: {e}")
            return [
                ModelInfo("anthropic/claude-sonnet-4-6", "openrouter", ["text", "vision"]),
                ModelInfo("openai/gpt-4o", "openrouter", ["text", "vision"]),
                ModelInfo("openai/gpt-4o-mini", "openrouter", ["text", "vision"]),
                ModelInfo("google/gemini-2.0-flash-001", "openrouter", ["text", "vision"]),
            ]

    def route(self, task_type: TaskType) -> Optional[ModelInfo]:
        """Route to appropriate OpenRouter model for task type."""
        if not self.available:
            return None
        if task_type not in (TaskType.TEXT, TaskType.VISION):
            return None

        if task_type == TaskType.VISION:
            return ModelInfo("openai/gpt-4o", "openrouter", ["text", "vision"])
        return ModelInfo("openai/gpt-4o-mini", "openrouter", ["text", "vision"])
    
    def chat(self, model: str, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Send chat request to OpenRouter (OpenAI-compatible API)."""
        if not self.available:
            return {"status": "error", "error": "OpenRouter provider not available"}

        try:
            # OpenRouter uses OpenAI-compatible chat/completions format
            api_messages = []
            for msg in messages:
                api_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

            payload = {
                "model": model,
                "messages": api_messages,
                "max_tokens": kwargs.get("max_tokens", 2048),
            }
            if "temperature" in kwargs:
                payload["temperature"] = kwargs["temperature"]

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://sonia.local",
                "X-Title": "Sonia AI Companion",
            }

            response = httpx.post(
                f"{self.endpoint}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            # Extract from OpenAI-compatible response
            choices = data.get("choices", [])
            text = ""
            finish_reason = None
            if choices:
                choice = choices[0]
                message = choice.get("message", {})
                text = message.get("content", "")
                finish_reason = choice.get("finish_reason")

            usage = data.get("usage", {})

            return {
                "status": "success",
                "model": data.get("model", model),
                "response": text,
                "metadata": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "finish_reason": finish_reason,
                },
            }

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                error_body = str(e)
            logger.error(f"OpenRouter API error ({e.response.status_code}): {error_body}")
            return {
                "status": "error",
                "error": f"OpenRouter API error: {error_body}",
                "model": model,
            }
        except Exception as e:
            logger.error(f"OpenRouter chat error: {e}")
            return {
                "status": "error",
                "error": str(e),
                "model": model,
            }


class ProviderRouter:
    """Routes requests to appropriate provider."""
    
    def __init__(self):
        """Initialize provider router."""
        self.providers: Dict[str, Provider] = {}
        self._init_providers()
    
    def _init_providers(self):
        """Initialize all configured providers."""
        # Ollama (always available)
        self.providers["ollama"] = OllamaProvider()
        
        # Anthropic (if configured)
        if os.getenv("ANTHROPIC_API_KEY"):
            self.providers["anthropic"] = AnthropicProvider()
        
        # OpenRouter (if configured)
        if os.getenv("OPENROUTER_API_KEY"):
            self.providers["openrouter"] = OpenRouterProvider()
        
        logger.info(f"Initialized {len(self.providers)} providers")
    
    def route(self, task_type: TaskType) -> Optional[ModelInfo]:
        """Route to best available provider for task."""
        # Priority: Ollama first (local), then Anthropic, then OpenRouter
        priority = ["ollama", "anthropic", "openrouter"]
        
        for provider_name in priority:
            if provider_name in self.providers:
                provider = self.providers[provider_name]
                if provider.available:
                    model = provider.route(task_type)
                    if model:
                        return model
        
        logger.warning(f"No available provider for task: {task_type.value}")
        return None
    
    def get_all_models(self) -> Dict[str, List[ModelInfo]]:
        """Get all available models from all providers."""
        models = {}
        
        for name, provider in self.providers.items():
            if provider.available:
                provider_models = provider.get_models()
                if provider_models:
                    models[name] = provider_models
        
        return models
    
    def chat(self, task_type: TaskType, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Send chat request, routing to best available provider."""
        # Try providers in priority order until one succeeds
        priority = ["ollama", "anthropic", "openrouter"]
        last_error = None

        for provider_name in priority:
            if provider_name not in self.providers:
                continue
            provider = self.providers[provider_name]
            if not provider.available:
                continue
            model_info = provider.route(task_type)
            if not model_info:
                continue

            result = provider.chat(model_info.name, messages, **kwargs)
            if result.get("status") == "success":
                return result
            # Record error but try next provider
            last_error = result.get("error", "unknown error")
            logger.warning(f"Provider {provider_name} failed: {last_error}, trying next")

        return {
            "status": "error",
            "error": last_error or f"No available provider for task: {task_type.value}",
        }


# Global router instance
_router = None


def get_router() -> ProviderRouter:
    """Get or create global provider router."""
    global _router
    if _router is None:
        _router = ProviderRouter()
    return _router
