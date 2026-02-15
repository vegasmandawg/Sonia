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
    
    # ── Identity / Session / History (M2) ──────────────────────────────────

    async def lookup_user_by_key(
        self,
        api_key_hash: str,
        correlation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Look up active user by API key hash. Returns None if not found."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v1/users/by-key"
        try:
            response = await self._retry_request("GET", url, correlation_id, params={"api_key_hash": api_key_hash})
            if response.status_code == 404:
                return None
            if response.status_code == 200:
                return response.json()
            return None
        except MemoryClientError:
            return None

    async def persist_session(
        self,
        session_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a session record to memory-engine."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v1/sessions/persist"
        response = await self._retry_request("POST", url, correlation_id, json=session_data)
        return response.json()

    async def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update fields on a persisted session."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v1/sessions/update/{session_id}"
        response = await self._retry_request("PUT", url, correlation_id, json=updates)
        return response.json()

    async def load_active_sessions(
        self,
        correlation_id: Optional[str] = None,
    ) -> list:
        """Load all active sessions from durable storage."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v1/sessions/active"
        try:
            response = await self._retry_request("GET", url, correlation_id)
            if response.status_code == 200:
                return response.json().get("sessions", [])
            return []
        except MemoryClientError:
            return []

    async def write_turn(
        self,
        turn_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Write a conversation turn to history. Fire-and-forget safe."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v1/history/turns"
        try:
            response = await self._retry_request("POST", url, correlation_id, json=turn_data)
            if response.status_code == 200:
                return response.json()
            return None
        except MemoryClientError:
            return None

    # ── V3 Memory Operations (M3) ──────────────────────────────────────────

    async def store_typed(
        self,
        memory_type: str,
        subtype: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a typed memory via v3 endpoint."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v3/memory/store"
        payload: Dict[str, Any] = {
            "type": memory_type,
            "subtype": subtype,
            "content": content,
        }
        if metadata:
            payload["metadata"] = metadata
        if valid_from:
            payload["valid_from"] = valid_from
        if valid_until:
            payload["valid_until"] = valid_until

        response = await self._retry_request("POST", url, correlation_id, json=payload)
        if response.status_code == 400:
            raise MemoryClientError("VALIDATION_FAILED", response.text[:300])
        if response.status_code != 200:
            raise MemoryClientError("STORE_TYPED_FAILED", f"status={response.status_code}")
        return response.json()

    async def query_with_budget(
        self,
        query: str,
        limit: int = 10,
        max_chars: int = 7000,
        type_filters: Optional[list] = None,
        include_redacted: bool = False,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Query memories with DB-level budget."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v3/memory/query"
        payload: Dict[str, Any] = {"query": query, "limit": limit, "max_chars": max_chars}
        if type_filters:
            payload["type_filters"] = type_filters
        if include_redacted:
            payload["include_redacted"] = True

        response = await self._retry_request("POST", url, correlation_id, json=payload)
        if response.status_code != 200:
            raise MemoryClientError("QUERY_FAILED", f"status={response.status_code}")
        return response.json()

    async def get_version_history(
        self,
        memory_id: str,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get version history for a memory."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v3/memory/{memory_id}/versions"
        response = await self._retry_request("GET", url, correlation_id)
        if response.status_code == 404:
            return {"versions": [], "count": 0}
        return response.json()

    async def create_version(
        self,
        original_id: str,
        new_content: str,
        metadata: Optional[Dict[str, Any]] = None,
        valid_from: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new version superseding an existing memory."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v3/memory/version"
        payload: Dict[str, Any] = {"original_id": original_id, "new_content": new_content}
        if metadata:
            payload["metadata"] = metadata
        if valid_from:
            payload["valid_from"] = valid_from

        response = await self._retry_request("POST", url, correlation_id, json=payload)
        if response.status_code == 409:
            raise MemoryClientError("CONCURRENT_SUPERSEDE", response.text[:200])
        if response.status_code != 200:
            raise MemoryClientError("VERSION_FAILED", f"status={response.status_code}")
        return response.json()

    async def redact_memory(
        self,
        memory_id: str,
        reason: str,
        performed_by: str = "system",
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Redact a memory."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v3/memory/redact"
        payload = {"memory_id": memory_id, "reason": reason, "performed_by": performed_by}
        response = await self._retry_request("POST", url, correlation_id, json=payload)
        return response.json()

    async def list_conflicts(
        self,
        memory_id: Optional[str] = None,
        resolved: Optional[bool] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List memory conflicts."""
        correlation_id = correlation_id or str(uuid.uuid4())
        url = f"{self.base_url}/v3/memory/conflicts"
        params: Dict[str, Any] = {}
        if memory_id:
            params["memory_id"] = memory_id
        if resolved is not None:
            params["resolved"] = str(resolved).lower()
        response = await self._retry_request("GET", url, correlation_id, params=params)
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
