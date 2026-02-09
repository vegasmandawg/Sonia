"""
API Gateway - Memory Engine Client
HTTP client for Memory Engine service (7020) with retry and timeout handling.
"""

import httpx
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime
import uuid

# HTTP client configuration
DEFAULT_TIMEOUT = 10.0  # 10 seconds
DEFAULT_RETRIES = 3
BACKOFF_FACTOR = 1.5


class MemoryClientError(Exception):
    """Memory Engine client error."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


class MemoryClient:
    """
    HTTP client for Memory Engine service.
    Handles retries, timeouts, and correlation ID propagation.
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:7020", timeout: float = DEFAULT_TIMEOUT):
        """
        Initialize Memory Engine client.
        
        Args:
            base_url: Base URL of Memory Engine service
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
        """
        Make HTTP request with exponential backoff retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL to request
            correlation_id: Correlation ID for tracing
            **kwargs: Additional httpx request arguments
        
        Returns:
            HTTP response
        
        Raises:
            MemoryClientError: On failure after retries
        """
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
                
                # Don't retry on 4xx errors (client errors)
                if 400 <= response.status_code < 500:
                    return response
                
                # Retry on 5xx errors and timeouts
                if response.status_code >= 500:
                    last_error = f"Server error: {response.status_code}"
                    if attempt < DEFAULT_RETRIES - 1:
                        await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                        continue
                    raise MemoryClientError(
                        "UNAVAILABLE",
                        f"Memory Engine returned {response.status_code}",
                        {"status_code": response.status_code}
                    )
                
                return response
            
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise MemoryClientError(
                    "TIMEOUT",
                    f"Memory Engine request timed out after {DEFAULT_RETRIES} retries",
                    {"timeout_seconds": self.timeout.timeout}
                )
            
            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise MemoryClientError(
                    "UNAVAILABLE",
                    f"Memory Engine unavailable: {str(e)}",
                    {"error": str(e)}
                )
        
        raise MemoryClientError(
            "UNAVAILABLE",
            f"Memory Engine request failed: {last_error}",
            {"last_error": last_error}
        )
    
    async def store(
        self,
        content: str,
        memory_type: str,
        metadata: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Store a memory in Memory Engine.
        
        Args:
            content: Memory content
            memory_type: Type of memory (e.g., "fact", "preference")
            metadata: Optional metadata
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Stored memory data
        
        Raises:
            MemoryClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/store"
        payload = {
            "content": content,
            "type": memory_type,
            "metadata": metadata or {}
        }
        
        response = await self._retry_request(
            "POST",
            url,
            correlation_id,
            json=payload
        )
        
        if response.status_code != 200:
            raise MemoryClientError(
                "STORE_FAILED",
                f"Failed to store memory: {response.status_code}",
                {"status_code": response.status_code, "response": response.text[:200]}
            )
        
        return response.json()
    
    async def recall(
        self,
        memory_id: str,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve a memory from Memory Engine.
        
        Args:
            memory_id: Memory ID to retrieve
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Memory data
        
        Raises:
            MemoryClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/recall/{memory_id}"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code == 404:
            raise MemoryClientError(
                "NOT_FOUND",
                f"Memory {memory_id} not found",
                {"memory_id": memory_id}
            )
        
        if response.status_code != 200:
            raise MemoryClientError(
                "RECALL_FAILED",
                f"Failed to recall memory: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search memories in Memory Engine.
        
        Args:
            query: Search query
            limit: Maximum results to return
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Search results
        
        Raises:
            MemoryClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/search"
        payload = {
            "query": query,
            "limit": limit
        }
        
        response = await self._retry_request(
            "POST",
            url,
            correlation_id,
            json=payload
        )
        
        if response.status_code != 200:
            raise MemoryClientError(
                "SEARCH_FAILED",
                f"Failed to search memories: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def get_status(
        self,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get Memory Engine service status.
        
        Args:
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Service status
        
        Raises:
            MemoryClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/status"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code != 200:
            raise MemoryClientError(
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
