"""
API Gateway — API Key Authentication Middleware (M2)

Validates Bearer tokens against memory-engine user store.
Caches valid keys in-memory to avoid per-request DB calls.

Config:
    auth.enabled: bool (default true)
    auth.exempt_paths: list of path prefixes that skip auth
    auth.service_token: shared token for service-to-service calls
    auth.key_cache_ttl_seconds: cache TTL (default 300)
    auth.key_cache_max_entries: max cache size (default 100)
"""

import enum
import functools
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional, Dict, Set, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("api-gateway.auth")

# Paths that never require authentication
_DEFAULT_EXEMPT = {
    "/healthz", "/health", "/status", "/", "/docs", "/openapi.json", "/redoc",
}


# ── Role-Based Access Control ──────────────────────────────────────────────

class Role(str, enum.Enum):
    """Operator roles for RBAC enforcement."""
    OPERATOR = "operator"    # Can mutate: tasks, approvals, policy toggles, restarts
    OBSERVER = "observer"    # Read-only: diagnostics, health, list endpoints

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._value2member_map_


# Valid roles for quick lookup
_VALID_ROLES = {r.value for r in Role}


def require_role(allowed_role: str):
    """Decorator/wrapper that enforces role-based access on an endpoint handler.

    Checks request.state.user_role against allowed_role.
    Returns 403 if role is missing, invalid, or insufficient.

    The operator role implicitly includes observer access (superset).
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(request: Request, *args, **kwargs):
            user_role = getattr(request.state, "user_role", None)

            # Missing role -> 403
            if not user_role:
                return JSONResponse(
                    status_code=403,
                    content={"error": "FORBIDDEN", "message": "No role claim present"},
                )

            # Invalid/unknown role -> 403
            if user_role not in _VALID_ROLES:
                return JSONResponse(
                    status_code=403,
                    content={"error": "FORBIDDEN", "message": f"Unknown role: {user_role}"},
                )

            # Role hierarchy: operator is superset of observer
            if allowed_role == "operator" and user_role != Role.OPERATOR.value:
                return JSONResponse(
                    status_code=403,
                    content={"error": "FORBIDDEN", "message": "Operator role required"},
                )

            # observer access: both operator and observer are allowed
            # (if allowed_role == "observer", any valid role passes)

            return await fn(request, *args, **kwargs)
        return wrapper
    return decorator


class _KeyCache:
    """LRU cache with TTL for validated API key -> user_id mappings."""

    def __init__(self, max_entries: int = 100, ttl_seconds: int = 300):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, Tuple[str, str, float]] = OrderedDict()
        # key_hash -> (user_id, display_name, cached_at)

    def get(self, key_hash: str) -> Optional[Dict[str, str]]:
        entry = self._cache.get(key_hash)
        if entry is None:
            return None
        user_id, display_name, cached_at = entry
        if time.time() - cached_at > self._ttl:
            del self._cache[key_hash]
            return None
        self._cache.move_to_end(key_hash)
        return {"user_id": user_id, "display_name": display_name}

    def put(self, key_hash: str, user_id: str, display_name: str) -> None:
        self._cache[key_hash] = (user_id, display_name, time.time())
        self._cache.move_to_end(key_hash)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def invalidate(self, key_hash: str) -> None:
        self._cache.pop(key_hash, None)

    def clear(self) -> None:
        self._cache.clear()


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that validates API key auth on all non-exempt paths."""

    def __init__(
        self,
        app,
        *,
        enabled: bool = True,
        exempt_paths: Optional[Set[str]] = None,
        service_token: str = "",
        memory_client=None,
        cache_ttl: int = 300,
        cache_max: int = 100,
    ):
        super().__init__(app)
        self.enabled = enabled
        self.exempt_paths = exempt_paths or _DEFAULT_EXEMPT
        self.service_token = service_token
        self.memory_client = memory_client  # MemoryClient for user lookup
        self._cache = _KeyCache(max_entries=cache_max, ttl_seconds=cache_ttl)

    def _is_exempt(self, path: str) -> bool:
        """Check if path is exempt from authentication."""
        for prefix in self.exempt_paths:
            if path == prefix or path.startswith(prefix + "/"):
                return True
        return False

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            request.state.user_id = None
            request.state.user_name = None
            request.state.user_role = None
            request.state.authenticated = False
            return await call_next(request)

        path = request.url.path

        # Exempt paths skip auth
        if self._is_exempt(path):
            request.state.user_id = None
            request.state.user_name = None
            request.state.user_role = None
            request.state.authenticated = False
            return await call_next(request)

        # Service-to-service token bypass
        svc_token = request.headers.get("x-service-token", "")
        if self.service_token and svc_token == self.service_token:
            request.state.user_id = "_service"
            request.state.user_name = "internal-service"
            request.state.user_role = Role.OPERATOR.value
            request.state.authenticated = True
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "UNAUTHORIZED", "message": "Missing or invalid Authorization header. Use: Bearer <api_key>"},
            )

        api_key = auth_header[7:].strip()
        if not api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "UNAUTHORIZED", "message": "Empty API key"},
            )

        key_hash = _hash_key(api_key)

        # Check cache first
        cached = self._cache.get(key_hash)
        if cached:
            request.state.user_id = cached["user_id"]
            request.state.user_name = cached["display_name"]
            request.state.user_role = cached.get("role", Role.OPERATOR.value)
            request.state.authenticated = True
            return await call_next(request)

        # Look up in memory-engine
        if not self.memory_client:
            logger.error("Auth enabled but no memory_client configured")
            return JSONResponse(
                status_code=503,
                content={"error": "AUTH_UNAVAILABLE", "message": "Auth service not configured"},
            )

        try:
            user_info = await self.memory_client.lookup_user_by_key(key_hash)
            if user_info is None:
                return JSONResponse(
                    status_code=401,
                    content={"error": "UNAUTHORIZED", "message": "Invalid API key"},
                )

            user_role = user_info.get("role", Role.OPERATOR.value)
            self._cache.put(key_hash, user_info["user_id"], user_info["display_name"])
            request.state.user_id = user_info["user_id"]
            request.state.user_name = user_info["display_name"]
            request.state.user_role = user_role
            request.state.authenticated = True
            return await call_next(request)

        except Exception as e:
            logger.error("Auth lookup failed: %s", e)
            return JSONResponse(
                status_code=503,
                content={"error": "AUTH_UNAVAILABLE", "message": "Authentication service unavailable"},
            )
