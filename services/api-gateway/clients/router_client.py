"""
API Gateway - Model Router Client
HTTP client for Model Router service (7010) with retry and timeout handling.
"""

import httpx
import asyncio
from typing import Optional, Dict, Any, List
import uuid

DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 3
BACKOFF_FACTOR = 1.5
FALLBACK_CONTRACT_VERSION = "1.0"

# Allowed fallback_trigger values (enum-like)
FALLBACK_TRIGGERS = frozenset({
    "router_unavailable",   # TIMEOUT or UNAVAILABLE from router
    "router_error",         # other RouterClientError (4xx, etc.)
    "unexpected_error",     # non-RouterClientError exception
})


def _fallback_envelope(
    message: str,
    trigger: str,
    correlation_id: str,
    exc: Exception,
) -> Dict[str, Any]:
    """Build a deterministic, machine-detectable fallback response."""
    return {
        "response": message,
        "source": "fallback",
        "model": "fallback",
        "provider": "static",
        "fallback_used": True,
        "fallback_trigger": trigger,
        "fallback_reason": f"{type(exc).__name__}: {exc}",
        "fallback_contract_version": FALLBACK_CONTRACT_VERSION,
        "correlation_id": correlation_id,
    }


class RouterClientError(Exception):
    """Model Router client error."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


class RouterClient:
    """
    HTTP client for Model Router service.
    Routes requests to appropriate LLM providers with fallback support.
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:7010", timeout: float = DEFAULT_TIMEOUT):
        """
        Initialize Model Router client.
        
        Args:
            base_url: Base URL of Model Router service
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)
        self.client = httpx.AsyncClient(timeout=self.timeout)
    
    async def _retry_request(
        self,
        method: str,
        url: str,
        correlation_id: str,
        **kwargs
    ) -> httpx.Response:
        """Make HTTP request with exponential backoff retry logic."""
        headers = kwargs.pop("headers", {})
        headers["X-Correlation-ID"] = correlation_id
        
        last_error = None
        
        for attempt in range(DEFAULT_RETRIES):
            try:
                response = await self.client.request(
                    method,
                    url,
                    headers=headers,
                    **kwargs
                )
                
                # Don't retry on 4xx errors
                if 400 <= response.status_code < 500:
                    return response
                
                # Retry on 5xx errors
                if response.status_code >= 500:
                    last_error = f"Server error: {response.status_code}"
                    if attempt < DEFAULT_RETRIES - 1:
                        await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                        continue
                    raise RouterClientError(
                        "UNAVAILABLE",
                        f"Model Router returned {response.status_code}",
                        {"status_code": response.status_code}
                    )
                
                return response
            
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise RouterClientError(
                    "TIMEOUT",
                    f"Model Router request timed out",
                    {"timeout_seconds": self.timeout.timeout}
                )
            
            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise RouterClientError(
                    "UNAVAILABLE",
                    f"Model Router unavailable: {str(e)}",
                    {"error": str(e)}
                )
        
        raise RouterClientError(
            "UNAVAILABLE",
            f"Model Router request failed: {last_error}",
            {"last_error": last_error}
        )
    
    async def route(
        self,
        task_type: str,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Route to best provider for task type.
        
        Args:
            task_type: Task type (TEXT, VISION, EMBEDDINGS, RERANKER)
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Routing decision with provider info
        
        Raises:
            RouterClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/route?task_type={task_type}"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code != 200:
            raise RouterClientError(
                "ROUTE_FAILED",
                f"Failed to route task: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        task_type: str = "text",
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get chat response from Model Router.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Optional specific model to use
            task_type: Task type for routing (text, vision, etc.)
            correlation_id: Optional correlation ID for tracing

        Returns:
            Chat response

        Raises:
            RouterClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())

        url = f"{self.base_url}/chat"
        payload = {
            "task_type": task_type,
            "messages": messages,
        }
        if model:
            payload["model"] = model
        
        response = await self._retry_request(
            "POST",
            url,
            correlation_id,
            json=payload
        )
        
        if response.status_code != 200:
            raise RouterClientError(
                "CHAT_FAILED",
                f"Failed to get chat response: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def chat_with_fallback(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        task_type: str = "text",
        correlation_id: Optional[str] = None,
        fallback_message: str = "(Model unavailable — please try again shortly.)",
    ) -> Dict[str, Any]:
        """
        Chat with automatic fallback on failure.

        If the primary chat() call fails (timeout, unavailable, error),
        returns a deterministic fallback response instead of raising.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Optional specific model to use
            task_type: Task type for routing
            correlation_id: Optional correlation ID for tracing
            fallback_message: Static message returned on failure

        Returns:
            Chat response dict. On failure, includes fallback_used=True.
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        try:
            result = await self.chat(
                messages=messages,
                model=model,
                task_type=task_type,
                correlation_id=correlation_id,
            )
            result["fallback_used"] = False
            return result
        except RouterClientError as exc:
            trigger = "router_unavailable" if exc.code in ("UNAVAILABLE", "TIMEOUT") else "router_error"
            return _fallback_envelope(fallback_message, trigger, correlation_id, exc)
        except Exception as exc:
            return _fallback_envelope(fallback_message, "unexpected_error", correlation_id, exc)

    async def get_models(
        self,
        task_type: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List available models.
        
        Args:
            task_type: Optional filter by task type
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Available models
        
        Raises:
            RouterClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/models"
        if task_type:
            url += f"?task_type={task_type}"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code != 200:
            raise RouterClientError(
                "MODELS_FAILED",
                f"Failed to get models: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def get_status(
        self,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get Model Router service status.
        
        Args:
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Service status
        
        Raises:
            RouterClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/status"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code != 200:
            raise RouterClientError(
                "STATUS_FAILED",
                f"Failed to get status: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
