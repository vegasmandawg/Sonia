"""
v4.6 Epic A — Gate A3: Role Enforcement Matrix Tests

Tests that operator/observer roles are enforced across api-gateway endpoints.
Uses structural validation (importable module checks) since the stack may not
be running during gate evaluation.
"""
import sys
import importlib.util
from pathlib import Path

# Load auth module directly
GW_DIR = Path(r"S:\services\api-gateway")
sys.path.insert(0, str(GW_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Load auth module ──
auth_mod = _load_module("auth", GW_DIR / "auth.py")


# ── A3 Test Matrix ──

def test_role_enum_exists():
    """Role enum defines operator and observer."""
    assert hasattr(auth_mod, "Role"), "Role enum not found in auth.py"
    role_cls = auth_mod.Role
    assert hasattr(role_cls, "OPERATOR"), "Role.OPERATOR not defined"
    assert hasattr(role_cls, "OBSERVER"), "Role.OBSERVER not defined"


def test_require_role_helper_exists():
    """require_role() helper/decorator is defined."""
    assert hasattr(auth_mod, "require_role"), "require_role not found in auth.py"
    fn = auth_mod.require_role
    assert callable(fn), "require_role must be callable"


def test_observer_denied_on_mutate():
    """Observer role cannot access mutating endpoints (require_role returns 403)."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    require_role = auth_mod.require_role

    async def mutate_endpoint(request: Request):
        return JSONResponse({"ok": True})

    guarded = require_role("operator")(mutate_endpoint)

    app = Starlette(routes=[Route("/test", guarded, methods=["POST"])])

    client = TestClient(app, raise_server_exceptions=False)

    # Simulate observer by setting request.state via middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    class InjectRole(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.authenticated = True
            request.state.user_id = "observer-user"
            request.state.user_role = "observer"
            return await call_next(request)

    app.add_middleware(InjectRole)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test")
    assert resp.status_code == 403, f"Observer should get 403, got {resp.status_code}"


def test_operator_allowed_on_mutate():
    """Operator role can access mutating endpoints."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    require_role = auth_mod.require_role

    async def mutate_endpoint(request: Request):
        return JSONResponse({"ok": True})

    guarded = require_role("operator")(mutate_endpoint)

    app = Starlette(routes=[Route("/test", guarded, methods=["POST"])])

    class InjectRole(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.authenticated = True
            request.state.user_id = "operator-user"
            request.state.user_role = "operator"
            return await call_next(request)

    app.add_middleware(InjectRole)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test")
    assert resp.status_code == 200, f"Operator should get 200, got {resp.status_code}"


def test_missing_role_denied():
    """Missing role claim results in 403."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    require_role = auth_mod.require_role

    async def mutate_endpoint(request: Request):
        return JSONResponse({"ok": True})

    guarded = require_role("operator")(mutate_endpoint)
    app = Starlette(routes=[Route("/test", guarded, methods=["POST"])])

    class InjectNoRole(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.authenticated = True
            request.state.user_id = "some-user"
            # user_role NOT set
            return await call_next(request)

    app.add_middleware(InjectNoRole)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test")
    assert resp.status_code == 403, f"Missing role should get 403, got {resp.status_code}"


def test_malformed_role_denied():
    """Malformed/unknown role results in 403."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    require_role = auth_mod.require_role

    async def mutate_endpoint(request: Request):
        return JSONResponse({"ok": True})

    guarded = require_role("operator")(mutate_endpoint)
    app = Starlette(routes=[Route("/test", guarded, methods=["POST"])])

    class InjectBadRole(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.authenticated = True
            request.state.user_id = "bad-user"
            request.state.user_role = "admin_superuser"  # invalid
            return await call_next(request)

    app.add_middleware(InjectBadRole)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test")
    assert resp.status_code == 403, f"Malformed role should get 403, got {resp.status_code}"


def test_role_attribution_in_response():
    """Role appears in auth context that handlers can use for audit."""
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    require_role = auth_mod.require_role

    async def audit_endpoint(request: Request):
        return JSONResponse({
            "actor_id": getattr(request.state, "user_id", None),
            "actor_role": getattr(request.state, "user_role", None),
        })

    guarded = require_role("operator")(audit_endpoint)
    app = Starlette(routes=[Route("/test", guarded, methods=["POST"])])

    class InjectRole(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.authenticated = True
            request.state.user_id = "op-user-42"
            request.state.user_role = "operator"
            return await call_next(request)

    app.add_middleware(InjectRole)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["actor_id"] == "op-user-42"
    assert body["actor_role"] == "operator"
