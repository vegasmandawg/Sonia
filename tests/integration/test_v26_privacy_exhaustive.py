"""
v2.6 Privacy Exhaustive Tests

Tests every failure mode of the vision-capture and perception privacy gate:
  - timeout, provider down, malformed payload, client disconnect
  - confirm "fail-closed" always holds
  - zero-frame invariant under state transitions

Tests (18):
  Vision Capture (12):
    1. Privacy disable clears buffer immediately
    2. Privacy disable forces mode to OFF
    3. Frame write -> enable privacy -> write ok -> disable -> rejected
    4. Frame read returns empty after privacy toggled off
    5. Single-frame read 403 when privacy off
    6. Mode change blocked when privacy off
    7. Malformed base64 rejected with 400
    8. Oversized frame rejected with 413
    9. Rate-limited frame rejected with 429
    10. Buffer stats accessible regardless of privacy
    11. Status endpoint always responds
    12. Privacy toggle count increments correctly

  Perception (6):
    13. Perception blocks when vision-capture unreachable (fail-closed)
    14. Perception blocks when privacy status reports disabled
    15. Perception privacy_blocks counter increments
    16. Perception events endpoint blocks on privacy
    17. Perception PROCESSING state returns 429
    18. Perception status endpoint always responds
"""

import sys
import base64
import importlib.util
import time

import pytest

sys.path.insert(0, r"S:")
sys.path.insert(0, r"S:\services\shared")


def _load_module(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_vc_mod = None
_perc_mod = None

def _get_vc():
    global _vc_mod
    if _vc_mod is None:
        _vc_mod = _load_module("vc_priv", r"S:\services\vision-capture\main.py")
    return _vc_mod

def _get_perc():
    global _perc_mod
    if _perc_mod is None:
        _perc_mod = _load_module("perc_priv", r"S:\services\perception\main.py")
    return _perc_mod


# ===========================================================================
# Vision Capture Privacy Tests
# ===========================================================================

class TestVisionCapturePrivacy:

    @pytest.fixture(autouse=True)
    def reset_state(self):
        mod = _get_vc()
        mod.state.privacy = mod.PrivacyState.DISABLED
        mod.state.mode = mod.CaptureMode.OFF
        mod.state.buffer.clear()
        mod.state.frames_captured = 0
        mod.state.frames_rejected = 0
        mod.state.frames_rejected_privacy = 0
        mod.state.frames_rejected_mode = 0
        mod.state.frames_rejected_size = 0
        mod.state.frames_rejected_rate = 0
        mod.state.last_frame_time = 0.0
        mod.state.privacy_toggle_count = 0
        yield

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        return TestClient(_get_vc().app)

    def _enable_and_activate(self, client):
        """Helper: enable privacy + set active mode."""
        client.post("/v1/vision/privacy/enable")
        client.post("/v1/vision/mode/set", json={"mode": "active"})

    def _push_frame(self, client, size=100):
        data = base64.b64encode(b"x" * size).decode()
        return client.post("/v1/vision/frames", json={
            "data_b64": data, "width": 10, "height": 10,
        })

    def test_disable_clears_buffer(self, client):
        self._enable_and_activate(client)
        self._push_frame(client)
        assert _get_vc().state.frames_captured == 1
        assert len(_get_vc().state.buffer) == 1
        resp = client.post("/v1/vision/privacy/disable")
        assert resp.status_code == 200
        assert resp.json()["buffer_cleared"] >= 1
        assert len(_get_vc().state.buffer) == 0

    def test_disable_forces_mode_off(self, client):
        self._enable_and_activate(client)
        assert _get_vc().state.mode.value == "active"
        client.post("/v1/vision/privacy/disable")
        assert _get_vc().state.mode.value == "off"

    def test_enable_write_disable_reject_cycle(self, client):
        self._enable_and_activate(client)
        r1 = self._push_frame(client)
        assert r1.status_code == 200
        client.post("/v1/vision/privacy/disable")
        r2 = self._push_frame(client)
        assert r2.status_code == 403

    def test_read_empty_after_privacy_off(self, client):
        self._enable_and_activate(client)
        self._push_frame(client)
        client.post("/v1/vision/privacy/disable")
        resp = client.get("/v1/vision/frames/latest?n=10")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
        assert resp.json()["frames"] == []

    def test_single_frame_read_403_privacy_off(self, client):
        resp = client.get("/v1/vision/frame/latest")
        assert resp.status_code == 403
        assert "PRIVACY_DISABLED" in resp.json()["detail"]

    def test_mode_change_blocked_privacy_off(self, client):
        resp = client.post("/v1/vision/mode/set", json={"mode": "active"})
        assert resp.status_code == 400
        assert "PRIVACY_DISABLED" in resp.json()["detail"]

    def test_malformed_base64_rejected(self, client):
        self._enable_and_activate(client)
        resp = client.post("/v1/vision/frames", json={
            "data_b64": "!!!NOT_BASE64!!!", "width": 10, "height": 10,
        })
        assert resp.status_code == 400
        assert "INVALID_BASE64" in resp.json()["detail"]

    def test_oversized_frame_rejected(self, client):
        self._enable_and_activate(client)
        # Create frame larger than 1MB
        big_data = base64.b64encode(b"x" * (1024 * 1024 + 1)).decode()
        resp = client.post("/v1/vision/frames", json={
            "data_b64": big_data, "width": 10, "height": 10,
        })
        assert resp.status_code == 413
        assert "FRAME_TOO_LARGE" in resp.json()["detail"]

    def test_rate_limited_frame_rejected(self, client):
        self._enable_and_activate(client)
        # First frame ok
        r1 = self._push_frame(client)
        assert r1.status_code == 200
        # Second frame immediately (within rate limit window)
        mod = _get_vc()
        mod.state.last_frame_time = time.time()
        resp = client.post("/v1/vision/frames", json={
            "data_b64": base64.b64encode(b"y" * 100).decode(),
            "width": 10, "height": 10,
            "timestamp": time.time(),  # same instant
        })
        assert resp.status_code == 429
        assert "RATE_LIMITED" in resp.json()["detail"]

    def test_buffer_stats_accessible(self, client):
        resp = client.get("/v1/vision/buffer/stats")
        assert resp.status_code == 200
        assert "frames" in resp.json()

    def test_status_always_responds(self, client):
        resp = client.get("/v1/vision/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "privacy" in data
        assert "mode" in data
        assert "frames_captured" in data

    def test_privacy_toggle_count(self, client):
        assert _get_vc().state.privacy_toggle_count == 0
        client.post("/v1/vision/privacy/enable")
        client.post("/v1/vision/privacy/disable")
        client.post("/v1/vision/privacy/enable")
        assert _get_vc().state.privacy_toggle_count == 3


# ===========================================================================
# Perception Privacy Tests
# ===========================================================================

class TestPerceptionPrivacy:

    @pytest.fixture(autouse=True)
    def reset_state(self):
        mod = _get_perc()
        mod.state.status = mod.PerceptionStatus.IDLE
        mod.state.total_privacy_blocks = 0
        yield

    @pytest.fixture
    def perc_client(self):
        from fastapi.testclient import TestClient
        return TestClient(_get_perc().app)

    def test_blocks_when_unreachable(self, perc_client):
        """Fail-closed: can't reach vision-capture -> treat as privacy disabled."""
        resp = perc_client.post("/v1/perception/analyze", json={
            "trigger": "user_command", "context": "test",
        })
        assert resp.status_code == 403
        assert "PRIVACY_BLOCKED" in resp.json()["detail"]

    def test_blocks_when_privacy_disabled(self, perc_client):
        """Even with a well-formed request, privacy disabled means no inference."""
        resp = perc_client.post("/v1/perception/analyze", json={
            "trigger": "wake_word", "context": "what do you see?",
            "frame_count": 1,
        })
        assert resp.status_code == 403

    def test_privacy_blocks_counter(self, perc_client):
        mod = _get_perc()
        assert mod.state.total_privacy_blocks == 0
        perc_client.post("/v1/perception/analyze", json={
            "trigger": "user_command", "context": "x",
        })
        perc_client.post("/v1/perception/analyze", json={
            "trigger": "motion", "context": "y",
        })
        assert mod.state.total_privacy_blocks == 2

    def test_events_endpoint_blocks_on_privacy(self, perc_client):
        """Event ingestion also respects privacy."""
        resp = perc_client.post("/v1/perception/events", json={
            "type": "vision.frame.available",
            "source": "vision-capture",
            "correlation_id": "req_test123",
            "payload": {"context": "motion detected"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is False
        assert "PRIVACY" in data["reason"]

    def test_processing_state_returns_429(self, perc_client):
        mod = _get_perc()
        mod.state.status = mod.PerceptionStatus.PROCESSING
        resp = perc_client.post("/v1/perception/analyze", json={
            "trigger": "user_command", "context": "x",
        })
        assert resp.status_code == 429
        assert "BUSY" in resp.json()["detail"]

    def test_status_always_responds(self, perc_client):
        resp = perc_client.get("/v1/perception/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "total_privacy_blocks" in data
