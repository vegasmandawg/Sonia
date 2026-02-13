"""
v2.6 Cross-Track Integration Tests

Tests:
  Track A (5):
    1. Manifest schema strict validation rejects unknown keys
    2. Manifest deterministic build ID is reproducible
    3. Build ID changes with different file hashes
    4. Identity invariant enforcer catches CRITICAL violations
    5. Identity invariant enforcer passes clean conversations
    6. Severity threshold breach detection

  Track B (6):
    7. Vision capture starts with privacy disabled
    8. Vision capture rejects frames when privacy disabled (403)
    9. Vision capture zero-frame on read when privacy disabled
    10. Perception privacy check fails closed
    11. Perception SceneAnalysis always requires confirmation
    12. Perception rejects when busy (429)

  Cross-Track (5):
    13. EventEnvelope generates correlation IDs
    14. EventEnvelope.derive preserves correlation_id
    15. validate_envelope rejects missing type
    16. validate_envelope rejects empty correlation_id
    17. ensure_correlation_id preserves existing IDs

Total: 17 tests
"""

import sys
import importlib.util
import time
from pathlib import Path

import pytest
pytestmark = [pytest.mark.legacy_v26_v28]

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

sys.path.insert(0, r"S:")
sys.path.insert(0, r"S:\services\shared")

# ---------------------------------------------------------------------------
# Module loaders (avoid sys.path collision between services)
# ---------------------------------------------------------------------------

def _load_module(name: str, filepath: str):
    """Load a Python module from an explicit file path."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # register so @dataclass can find it
    spec.loader.exec_module(mod)
    return mod


# Cache loaded modules at module level so fixtures share state
_vc_mod = None
_perc_mod = None


def _get_vc_mod():
    global _vc_mod
    if _vc_mod is None:
        _vc_mod = _load_module("vision_capture_main", r"S:\services\vision-capture\main.py")
    return _vc_mod


def _get_perc_mod():
    global _perc_mod
    if _perc_mod is None:
        _perc_mod = _load_module("perception_main", r"S:\services\perception\main.py")
    return _perc_mod


# ---------------------------------------------------------------------------
# Track A: Manifest + Invariants
# ---------------------------------------------------------------------------

class TestTrackAManifest:
    """Manifest schema validation tests."""

    def test_reject_unknown_keys(self):
        """Strict mode rejects unknown top-level keys."""
        from datasets.manifests.schema import DatasetManifest, ManifestValidationError

        data = {
            "name": "test",
            "version": "1.0.0",
            "source": "unit_test",
            "license": "MIT",
            "schema_version": "1.1.0",
            "created_at": "2026-02-09T00:00:00Z",
            "description": "test",
            "provenance": {
                "author": "test",
                "created_at": "2026-02-09T00:00:00Z",
                "tool_version": "2.6.0",
            },
            "UNKNOWN_KEY": "should_fail",
        }
        with pytest.raises(ManifestValidationError, match="Unknown key"):
            DatasetManifest._from_dict(data)

    def test_deterministic_build_id(self):
        """Same inputs produce same build ID."""
        from datasets.manifests.schema import DatasetManifest, Provenance, FileEntry

        prov = Provenance(author="test", created_at="2026-01-01", tool_version="2.6.0")
        m1 = DatasetManifest(
            name="test", version="1.0", source="s", license="MIT", provenance=prov,
            files=[FileEntry(relative_path="a.jsonl", sha256="abc123", size_bytes=100)],
        )
        m2 = DatasetManifest(
            name="test", version="1.0", source="s", license="MIT", provenance=prov,
            files=[FileEntry(relative_path="a.jsonl", sha256="abc123", size_bytes=100)],
        )
        id1 = m1.compute_build_id()
        id2 = m2.compute_build_id()
        assert id1 == id2
        assert len(id1) == 16

    def test_build_id_changes_with_files(self):
        """Different file hashes produce different build IDs."""
        from datasets.manifests.schema import DatasetManifest, Provenance, FileEntry

        prov = Provenance(author="test", created_at="2026-01-01", tool_version="2.6.0")
        m1 = DatasetManifest(
            name="test", version="1.0", source="s", license="MIT", provenance=prov,
            files=[FileEntry(relative_path="a.jsonl", sha256="aaa", size_bytes=100)],
        )
        m2 = DatasetManifest(
            name="test", version="1.0", source="s", license="MIT", provenance=prov,
            files=[FileEntry(relative_path="a.jsonl", sha256="bbb", size_bytes=100)],
        )
        assert m1.compute_build_id() != m2.compute_build_id()


class TestTrackAInvariants:
    """Identity invariant enforcement tests."""

    def test_catches_critical_violations(self):
        """Enforcer catches CRITICAL name claims."""
        from pipeline.text.identity_invariants import (
            IdentityInvariantEnforcer, get_test_fixtures,
        )
        _, violating = get_test_fixtures()
        enforcer = IdentityInvariantEnforcer(mode="enforce")
        passed, report = enforcer.process(violating)

        assert report.severity_counts["CRITICAL"] >= 2
        assert report.conversations_removed > 0
        assert len(report.violations) > 0

    def test_passes_clean_conversations(self):
        """Enforcer passes clean conversations without violations."""
        from pipeline.text.identity_invariants import (
            IdentityInvariantEnforcer, get_test_fixtures,
        )
        clean, _ = get_test_fixtures()
        enforcer = IdentityInvariantEnforcer(mode="enforce")
        passed, report = enforcer.process(clean)

        assert len(report.violations) == 0
        assert report.conversations_passed == len(clean)
        assert report.conversations_removed == 0

    def test_threshold_breach_detection(self):
        """Enforcer detects when severity thresholds are breached."""
        from pipeline.text.identity_invariants import (
            IdentityInvariantEnforcer, get_test_fixtures,
        )
        _, violating = get_test_fixtures()
        enforcer = IdentityInvariantEnforcer(
            mode="enforce",
            severity_thresholds={"CRITICAL": 0, "MAJOR": 0, "MINOR": 0},
        )
        _, report = enforcer.process(violating)

        assert report.threshold_breach is True
        assert len(report.breach_details) > 0


# ---------------------------------------------------------------------------
# Track B: Vision Capture + Perception
# ---------------------------------------------------------------------------

class TestTrackBVisionCapture:
    """Vision capture privacy and frame handling tests."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        mod = _get_vc_mod()
        # Reset state for each test
        mod.state.privacy = mod.PrivacyState.DISABLED
        mod.state.mode = mod.CaptureMode.OFF
        mod.state.buffer.clear()
        return TestClient(mod.app)

    def test_starts_privacy_disabled(self, client):
        """Vision capture starts with privacy=disabled, mode=off."""
        resp = client.get("/v1/vision/privacy/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["privacy"] == "disabled"
        assert data["capture_allowed"] is False

    def test_rejects_frames_privacy_disabled(self, client):
        """Frames rejected with 403 when privacy disabled."""
        import base64
        frame_data = base64.b64encode(b"fake_frame_data").decode()
        resp = client.post("/v1/vision/frames", json={
            "data_b64": frame_data,
            "width": 320,
            "height": 240,
        })
        assert resp.status_code == 403
        assert "PRIVACY_DISABLED" in resp.json()["detail"]

    def test_zero_frame_on_read_privacy_disabled(self, client):
        """Reading frames returns empty list when privacy disabled."""
        resp = client.get("/v1/vision/frames/latest?n=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["frames"] == []
        assert data["privacy"] == "disabled"


class TestTrackBPerception:
    """Perception pipeline tests."""

    @pytest.fixture
    def perc_client(self):
        from fastapi.testclient import TestClient
        mod = _get_perc_mod()
        # Reset state
        mod.state.status = mod.PerceptionStatus.IDLE
        return TestClient(mod.app)

    def test_privacy_check_fails_closed(self, perc_client):
        """Perception rejects analysis when vision privacy is disabled."""
        resp = perc_client.post("/v1/perception/analyze", json={
            "trigger": "user_command",
            "context": "test",
        })
        # Should be 403 (privacy blocked) since vision-capture is not running
        # and fail-closed treats unreachable as privacy disabled
        assert resp.status_code == 403
        assert "PRIVACY_BLOCKED" in resp.json()["detail"]

    def test_scene_analysis_requires_confirmation(self):
        """SceneAnalysis.action_requires_confirmation is always True."""
        mod = _get_perc_mod()
        SceneAnalysis = mod.SceneAnalysis

        scene = SceneAnalysis(
            scene_id="test-001",
            timestamp=time.time(),
            trigger="user_command",
            summary="Test scene",
            overall_confidence=0.9,
            action_requires_confirmation=False,  # try to set False
            inference_ms=50.0,
        )
        # Pydantic validator forces it True
        assert scene.action_requires_confirmation is True

    def test_rejects_when_busy(self, perc_client):
        """Perception returns 429 when already processing."""
        mod = _get_perc_mod()
        old_status = mod.state.status
        mod.state.status = mod.PerceptionStatus.PROCESSING
        try:
            resp = perc_client.post("/v1/perception/analyze", json={
                "trigger": "user_command",
                "context": "test",
            })
            assert resp.status_code == 429
            assert "BUSY" in resp.json()["detail"]
        finally:
            mod.state.status = old_status


# ---------------------------------------------------------------------------
# Cross-Track: Event Envelope + Correlation
# ---------------------------------------------------------------------------

class TestCrossTrackEvents:
    """Unified event envelope and correlation ID tests."""

    def test_envelope_generates_correlation_id(self):
        """EventEnvelope auto-generates correlation_id."""
        from services.shared.events import EventEnvelope

        env = EventEnvelope(type="test.event", source="unit_test")
        assert env.correlation_id.startswith("req_")
        assert len(env.correlation_id) == 16  # "req_" + 12 hex chars
        assert env.id  # UUID generated
        assert env.timestamp > 0

    def test_envelope_derive_preserves_correlation(self):
        """EventEnvelope.derive() carries correlation_id to child events."""
        from services.shared.events import EventEnvelope, EventType

        parent = EventEnvelope(
            type=EventType.FRAME_AVAILABLE,
            source="vision-capture",
            correlation_id="req_parent12345",
        )
        child = parent.derive(
            event_type=EventType.PERCEPTION_COMPLETED,
            source="perception",
            payload={"scene_id": "s001"},
        )
        assert child.correlation_id == "req_parent12345"
        assert child.source == "perception"
        assert child.type == EventType.PERCEPTION_COMPLETED
        assert child.id != parent.id  # unique ID

    def test_validate_rejects_missing_type(self):
        """validate_envelope rejects envelope without type."""
        from services.shared.events import validate_envelope

        valid, err = validate_envelope({"correlation_id": "req_abc"})
        assert valid is False
        assert "type" in err

    def test_validate_rejects_empty_correlation(self):
        """validate_envelope rejects empty correlation_id."""
        from services.shared.events import validate_envelope

        valid, err = validate_envelope({"type": "test", "correlation_id": ""})
        assert valid is False
        assert "correlation_id" in err

    def test_ensure_correlation_preserves_existing(self):
        """ensure_correlation_id returns existing non-empty ID."""
        from services.shared.events import ensure_correlation_id

        assert ensure_correlation_id("req_existing") == "req_existing"
        generated = ensure_correlation_id("")
        assert generated.startswith("req_")
        generated2 = ensure_correlation_id(None)
        assert generated2.startswith("req_")
