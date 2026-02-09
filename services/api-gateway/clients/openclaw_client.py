"""
API Gateway - OpenClaw Client
HTTP client for OpenClaw service (7040) with retry and timeout handling.
"""

import httpx
import asyncio
from typing import Optional, Dict, Any
import uuid

DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 3
BACKOFF_FACTOR = 1.5


class OpenclawClientError(Exception):
    """OpenClaw client error."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


class OpenclawClient:
    """
    HTTP client for OpenClaw executor registry service.
    Handles tool execution with safety policy enforcement.
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:7040", timeout: float = DEFAULT_TIMEOUT):
        """
        Initialize OpenClaw client.
        
        Args:
            base_url: Base URL of OpenClaw service
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
                    raise OpenclawClientError(
                        "UNAVAILABLE",
                        f"OpenClaw returned {response.status_code}",
                        {"status_code": response.status_code}
                    )
                
                return response
            
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise OpenclawClientError(
                    "TIMEOUT",
                    f"OpenClaw request timed out",
                    {"timeout_seconds": self.timeout.timeout}
                )
            
            except httpx.RequestError as e:
                last_error = f"Request error: {str(e)}"
                if attempt < DEFAULT_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                raise OpenclawClientError(
                    "UNAVAILABLE",
                    f"OpenClaw unavailable: {str(e)}",
                    {"error": str(e)}
                )
        
        raise OpenclawClientError(
            "UNAVAILABLE",
            f"OpenClaw request failed: {last_error}",
            {"last_error": last_error}
        )
    
    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        timeout_ms: int = 5000,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a tool in OpenClaw.
        
        Args:
            tool_name: Name of tool (e.g., 'shell.run', 'file.read')
            args: Tool arguments
            timeout_ms: Execution timeout in milliseconds
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Execution result
        
        Raises:
            OpenclawClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/execute"
        payload = {
            "tool_name": tool_name,
            "args": args,
            "timeout_ms": timeout_ms,
            "correlation_id": correlation_id
        }
        
        response = await self._retry_request(
            "POST",
            url,
            correlation_id,
            json=payload
        )
        
        if response.status_code != 200:
            raise OpenclawClientError(
                "EXECUTE_FAILED",
                f"Failed to execute tool: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def list_tools(
        self,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all available tools.
        
        Args:
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Tool list
        
        Raises:
            OpenclawClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/tools"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code != 200:
            raise OpenclawClientError(
                "LIST_FAILED",
                f"Failed to list tools: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def get_tool(
        self,
        tool_name: str,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get specific tool metadata.
        
        Args:
            tool_name: Name of tool
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Tool metadata
        
        Raises:
            OpenclawClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/tools/{tool_name}"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code == 404:
            raise OpenclawClientError(
                "NOT_FOUND",
                f"Tool {tool_name} not found",
                {"tool_name": tool_name}
            )
        
        if response.status_code != 200:
            raise OpenclawClientError(
                "GET_TOOL_FAILED",
                f"Failed to get tool: {response.status_code}",
                {"status_code": response.status_code}
            )
        
        return response.json()
    
    async def get_status(
        self,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get OpenClaw service status.
        
        Args:
            correlation_id: Optional correlation ID for tracing
        
        Returns:
            Service status
        
        Raises:
            OpenclawClientError: On failure
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        
        url = f"{self.base_url}/status"
        
        response = await self._retry_request(
            "GET",
            url,
            correlation_id
        )
        
        if response.status_code != 200:
            raise OpenclawClientError(
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
