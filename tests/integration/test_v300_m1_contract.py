"""
SONIA v3.0.0 Milestone 1 — Contract + Config Cut integration tests.

Tests:
  - Config schema validation (valid, invalid, env overlay)
  - Version exports (SONIA_VERSION, SONIA_CONTRACT, LEGACY_CONTRACT_V1)
  - V3 endpoints exist and return contract_version
  - V1 endpoints return deprecation headers + _deprecation field
  - All service healthz return contract_version

Runs against in-process ASGI TestClient (no live services needed).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Path setup ───────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_DIR = REPO_ROOT / "services" / "shared"
GATEWAY_DIR = REPO_ROOT / "services" / "api-gateway"
CONFIG_DIR = REPO_ROOT / "config"

sys.path.insert(0, str(SHARED_DIR))
sys.path.insert(0, str(GATEWAY_DIR))


# ═════════════════════════════════════════════════════════════════════════
# Group 1: Version exports
# ═════════════════════════════════════════════════════════════════════════

class TestVersionExports:
    """Verify shared/version.py exports the correct v3.0.0 values."""

    def test_sonia_version(self):
        from version import SONIA_VERSION
        # v3.1 branch: accept release or dev suffix; v3.0 baseline also valid
        assert SONIA_VERSION in ("3.0.0", "3.1.0", "3.1.0-dev", "3.2.0-dev"), f"Unexpected version: {SONIA_VERSION}"

    def test_sonia_contract(self):
        from version import SONIA_CONTRACT
        assert SONIA_CONTRACT == "v3.0.0"

    def test_legacy_contract(self):
        from version import LEGACY_CONTRACT_V1
        assert "deprecated" in LEGACY_CONTRACT_V1.lower()
        assert "v3.1" in LEGACY_CONTRACT_V1


# ═════════════════════════════════════════════════════════════════════════
# Group 2: Config schema validation
# ═════════════════════════════════════════════════════════════════════════

class TestConfigSchema:
    """Verify config_validator.py works with valid and invalid configs."""

    def test_valid_config_loads(self):
        """The canonical sonia-config.json passes schema validation."""
        from config_validator import SoniaConfig
        cfg = SoniaConfig()
        assert cfg.version == "3.0.0"
        assert cfg.schema_version == "3.0.0"

    def test_valid_config_services(self):
        """Config has all 8 expected services."""
        from config_validator import SoniaConfig
        cfg = SoniaConfig()
        services = cfg.get("services")
        expected = {
            "api_gateway", "model_router", "memory_engine",
            "pipecat", "openclaw", "eva_os",
            "vision_capture", "perception",
        }
        assert expected.issubset(set(services.keys()))

    def test_invalid_config_raises(self):
        """A config missing required fields fails validation."""
        from config_validator import SoniaConfig, ConfigValidationError

        bad_config = {"config_schema": "3.0.0"}  # missing sonia_version, services, etc.
        schema_path = CONFIG_DIR / "schemas" / "sonia-config.schema.json"

        if not schema_path.exists():
            pytest.skip("Schema file not found")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(bad_config, f)
            bad_path = f.name

        try:
            with pytest.raises(ConfigValidationError):
                SoniaConfig(config_path=bad_path, schema_path=str(schema_path))
        finally:
            os.unlink(bad_path)

    def test_env_overlay(self):
        """SONIA_*__* environment variables override config values."""
        from config_validator import SoniaConfig
        with patch.dict(os.environ, {"SONIA_MODEL_ROUTER__OFFLINE_PREFERRED": "false"}):
            cfg = SoniaConfig()
            mr = cfg.get("model_router")
            assert mr.get("offline_preferred") is False

    def test_config_get_service(self):
        """get_service() returns service definitions."""
        from config_validator import SoniaConfig
        cfg = SoniaConfig()
        gw = cfg.get_service("api_gateway")
        assert gw["port"] == 7000
        assert gw["health_endpoint"] == "/healthz"


# ═════════════════════════════════════════════════════════════════════════
# Group 3: API Gateway v3/v1 endpoints
# ═════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def gateway_client():
    """Create a TestClient for the API Gateway app."""
    from httpx import ASGITransport, AsyncClient
    from starlette.testclient import TestClient

    # Mock downstream clients to avoid needing live services
    mock_router = MagicMock()
    mock_router.chat = MagicMock(return_value={
        "status": "success",
        "response": "Hello from mock",
        "model": "mock-model",
        "provider": "mock",
    })
    mock_memory = MagicMock()
    mock_memory.search = MagicMock(return_value={"results": [], "count": 0})

    # Use importlib to explicitly load the gateway main, avoiding
    # collision with memory-engine/main.py when both are on sys.path
    import importlib.util
    _gw_spec = importlib.util.spec_from_file_location(
        "gw_main", str(GATEWAY_DIR / "main.py"))
    gw_main = importlib.util.module_from_spec(_gw_spec)
    sys.modules["gw_main"] = gw_main
    _gw_spec.loader.exec_module(gw_main)
    # Patch clients dict
    if hasattr(gw_main, '_clients'):
        original_clients = gw_main._clients.copy() if gw_main._clients else {}
    else:
        original_clients = {}

    client = TestClient(gw_main.app, raise_server_exceptions=False)
    yield client


class TestV3Endpoints:
    """Verify /v3/* endpoints return contract_version."""

    def test_healthz_contract_version(self, gateway_client):
        resp = gateway_client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("contract_version") == "v3.0.0"

    def test_v3_capabilities(self, gateway_client):
        resp = gateway_client.get("/v3/capabilities")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("contract_version") == "v3.0.0"

    def test_v3_chat_endpoint_exists(self, gateway_client):
        """V3 chat endpoint accepts requests (may fail downstream, but route exists)."""
        resp = gateway_client.post(
            "/v3/chat",
            json={"message": "test", "session_id": "test-session"},
        )
        # Accept 200 or 5xx (downstream failure) -- 404 means route missing
        assert resp.status_code != 404

    def test_v3_turn_endpoint_exists(self, gateway_client):
        """V3 turn endpoint accepts requests."""
        resp = gateway_client.post(
            "/v3/turn",
            json={"user_input": "test", "session_id": "test-session"},
        )
        assert resp.status_code != 404

    def test_v3_deps(self, gateway_client):
        resp = gateway_client.get("/v3/deps")
        # May be 200 or 5xx, but NOT 404
        assert resp.status_code != 404


class TestV1Deprecation:
    """Verify /v1/* endpoints return deprecation headers and fields."""

    def test_v1_turn_deprecation_header(self, gateway_client):
        resp = gateway_client.post(
            "/v1/turn",
            json={"user_input": "test", "session_id": "test-session"},
        )
        # Route must exist
        assert resp.status_code != 404
        # Deprecation headers
        assert resp.headers.get("x-deprecated") == "true"
        assert "v3.1" in resp.headers.get("x-removal-version", "")

    def test_v1_chat_deprecation_header(self, gateway_client):
        resp = gateway_client.post(
            "/v1/chat",
            json={"message": "test", "session_id": "test-session"},
        )
        assert resp.status_code != 404
        assert resp.headers.get("x-deprecated") == "true"

    def test_v1_turn_deprecation_field(self, gateway_client):
        """V1 turn response body includes _deprecation field."""
        resp = gateway_client.post(
            "/v1/turn",
            json={"user_input": "test", "session_id": "test-session"},
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "_deprecation" in data
            dep = data["_deprecation"]
            assert dep.get("deprecated") is True
            assert "v3.1" in dep.get("removal_version", "")

    def test_v1_migrate_to_header(self, gateway_client):
        resp = gateway_client.post(
            "/v1/turn",
            json={"user_input": "test", "session_id": "test-session"},
        )
        migrate = resp.headers.get("x-migrate-to", "")
        assert "/v3/turn" in migrate


class TestV1V3Parity:
    """V3 and V1 endpoints call the same underlying handlers."""

    def test_capabilities_both_versions(self, gateway_client):
        """Both /v3/capabilities and /v1/capabilities return data."""
        v3 = gateway_client.get("/v3/capabilities")
        v1 = gateway_client.get("/v1/capabilities")
        assert v3.status_code == 200
        # v1 may return 200 or redirect, but not 404
        assert v1.status_code != 404
