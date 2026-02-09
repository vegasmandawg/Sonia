"""
Pipecat - API Gateway Client
HTTP client for calling API Gateway chat endpoint.
"""

import httpx
import asyncio
from typing import Optional, Dict, Any
import uuid

DEFAULT_TIMEOUT = 30.0  # Longer timeout for chat operations
DEFAULT_RETRIES = 3
BACKOFF_FACTOR = 1.5


class ApiGatewayClientError(Exception):
    """API Gateway client error."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


class ApiGatewayClient:
    """HTTP client for API Gateway service."""
    
    def __init__(self, base_url: str = "http://127.0.0.1:7000", timeout: float = DEFAULT_TIMEOUT):
        """
        Initialize API Gateway client.
        
        Args:
            base_url: Base URL of API Gateway
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
                    raise ApiGatewayClientError(
                        "UNAVAILABLE",
                        f"API Gateway returned {response.status_code}",
                        {"status_code": response.status_code}
                    )
                
                return response
            
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise ApiGatewayClientError(
                    "TIMEOUT",
                    f"API Gateway request timed out",
                    {"timeout_seconds": self.timeout.timeout}
                )
            
            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise ApiGatewayClientError(
                    "UNAVAILABLE",
                    f"API Gateway unavailable: {str(e)}",
                    {"error": str(e)}
                )
        
        raise ApiGatewayClientError(
            "UNAVAILABLE",
            f"API Gateway request failed: {last_error}",
            {"last_error": last_error}
        )
    
    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        model: Optional[str] = None
    ) -> str:
        """
        Send chat message to API Gateway.
        
        Args:
            message: User message
            session_id: Optional session ID for context
            correlation_id: Optional correlation ID for tracing
            model: Optional specific model to use
        
        Returns:
            Response text from chat endpoint
        
        Raises:
            ApiGatewayClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/v1/chat"
        params = {"message": message}
        if session_id:
            params["session_id"] = session_id
        if model:
            params["model"] = model
        
        response = await self._retry_request(
            "POST",
            url,
            correlation_id,
            params=params
        )
        
        if response.status_code != 200:
            raise ApiGatewayClientError(
                "CHAT_FAILED",
                f"Chat request failed: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        data = response.json()
        
        # Extract response text from standard envelope
        if data.get("ok") and data.get("data"):
            return data["data"].get("response", "No response")
        
        # On error, raise with error details
        if not data.get("ok"):
            error = data.get("error", {})
            raise ApiGatewayClientError(
                error.get("code", "UNKNOWN"),
                error.get("message", "Unknown error"),
                error.get("details")
            )
        
        return "No response"
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
