"""
Unit tests for M1: Default-on auth posture with SONIA_DEV_MODE bypass.

Tests the config matrix: prod mode, dev mode, missing env, malformed env.
No live services required.
"""
import os
import sys
import pytest

# Ensure api-gateway is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "api-gateway"))


class TestAuthPostureConfig:
    """Test auth posture determination logic (env-var driven)."""

    def _resolve_posture(self, env_value=None):
        """Simulate the auth posture resolution from main.py."""
        old = os.environ.pop("SONIA_DEV_MODE", None)
        try:
            if env_value is not None:
                os.environ["SONIA_DEV_MODE"] = env_value
            dev_mode = os.environ.get("SONIA_DEV_MODE", "").strip() == "1"
            auth_enabled = not dev_mode
            return {"auth_enabled": auth_enabled, "dev_mode": dev_mode}
        finally:
            os.environ.pop("SONIA_DEV_MODE", None)
            if old is not None:
                os.environ["SONIA_DEV_MODE"] = old

    def test_default_auth_enabled(self):
        """No env var set -> auth ON (production default)."""
        posture = self._resolve_posture(env_value=None)
        assert posture["auth_enabled"] is True
        assert posture["dev_mode"] is False

    def test_dev_mode_disables_auth(self):
        """SONIA_DEV_MODE=1 -> auth OFF."""
        posture = self._resolve_posture(env_value="1")
        assert posture["auth_enabled"] is False
        assert posture["dev_mode"] is True

    def test_dev_mode_zero_keeps_auth(self):
        """SONIA_DEV_MODE=0 -> auth ON (zero is not the bypass)."""
        posture = self._resolve_posture(env_value="0")
        assert posture["auth_enabled"] is True
        assert posture["dev_mode"] is False

    def test_empty_string_keeps_auth(self):
        """SONIA_DEV_MODE='' -> auth ON."""
        posture = self._resolve_posture(env_value="")
        assert posture["auth_enabled"] is True
        assert posture["dev_mode"] is False

    def test_malformed_env_keeps_auth(self):
        """SONIA_DEV_MODE=yes -> auth ON (only '1' is bypass)."""
        posture = self._resolve_posture(env_value="yes")
        assert posture["auth_enabled"] is True
        assert posture["dev_mode"] is False

    def test_whitespace_one_disables_auth(self):
        """SONIA_DEV_MODE=' 1 ' -> auth OFF (strip whitespace)."""
        posture = self._resolve_posture(env_value=" 1 ")
        assert posture["auth_enabled"] is False
        assert posture["dev_mode"] is True

    def test_true_string_keeps_auth(self):
        """SONIA_DEV_MODE=true -> auth ON (only exact '1')."""
        posture = self._resolve_posture(env_value="true")
        assert posture["auth_enabled"] is True
        assert posture["dev_mode"] is False


class TestAuthMiddlewareImport:
    """Verify auth middleware can be imported and instantiated."""

    def test_auth_middleware_importable(self):
        from auth import AuthMiddleware
        assert AuthMiddleware is not None

    def test_key_cache_importable(self):
        from auth import _KeyCache
        cache = _KeyCache(max_entries=10, ttl_seconds=5)
        assert cache is not None

    def test_key_cache_put_get(self):
        from auth import _KeyCache
        cache = _KeyCache(max_entries=10, ttl_seconds=300)
        cache.put("hash1", "user1", "User One")
        result = cache.get("hash1")
        assert result is not None
        assert result["user_id"] == "user1"

    def test_key_cache_eviction(self):
        from auth import _KeyCache
        cache = _KeyCache(max_entries=2, ttl_seconds=300)
        cache.put("a", "u1", "n1")
        cache.put("b", "u2", "n2")
        cache.put("c", "u3", "n3")  # should evict "a"
        assert cache.get("a") is None
        assert cache.get("c") is not None
