"""
v2.6 Contract Tests -- Schema Freeze Verification

Ensures frozen APIs (EventEnvelope, DatasetManifest, SceneAnalysis)
behave as documented and reject violations. These tests form the
release-confidence layer for the v2.6 GA gate.

Tests (22):
  EventEnvelope (10):
    1. All 20 EventType values are strings
    2. EventEnvelope roundtrip to JSON and back
    3. Unknown event type accepted (string field, not enum-locked)
    4. Empty payload produces valid envelope
    5. derive() sets new id/timestamp but keeps correlation_id
    6. validate_envelope accepts valid envelope dict
    7. validate_envelope rejects non-dict input
    8. validate_envelope rejects missing correlation_id key
    9. Correlation IDs are unique across calls
    10. EventType enum has exactly 20 members

  DatasetManifest (8):
    11. Manifest schema version is 1.1.0
    12. Manifest _from_dict roundtrip is lossless
    13. Manifest _from_dict rejects unknown provenance keys
    14. Manifest validate catches empty name
    15. SplitConfig validate catches ratios != 1.0
    16. InvariantConfig validate catches bad mode
    17. ExportConfig validate catches bad format
    18. compute_build_id is idempotent (call twice, same result)

  SceneAnalysis (4):
    19. action_requires_confirmation is True even when set False
    20. SceneAnalysis requires positive timestamp
    21. SceneAnalysis requires non-empty scene_id
    22. Entity confidence must be in [0, 1]
"""

import sys
import json
import time
import importlib.util

import pytest
pytestmark = [pytest.mark.legacy_v26_v28, pytest.mark.legacy_manifest_schema]

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

sys.path.insert(0, r"S:")
sys.path.insert(0, r"S:\services\shared")


def _load_module(name: str, filepath: str):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_perc_mod = None
def _get_perc_mod():
    global _perc_mod
    if _perc_mod is None:
        _perc_mod = _load_module("perception_main_ct", r"S:\services\perception\main.py")
    return _perc_mod


# ===========================================================================
# EventEnvelope contract tests
# ===========================================================================

class TestEventEnvelopeContract:

    def test_all_event_types_are_strings(self):
        from services.shared.events import EventType
        members = list(EventType)
        assert len(members) == 24  # 19 original + 5 supervisory (v2.9)
        for m in members:
            assert isinstance(m.value, str)

    def test_envelope_json_roundtrip(self):
        from services.shared.events import EventEnvelope, EventType
        env = EventEnvelope(
            type=EventType.TURN_STARTED,
            source="gateway",
            payload={"session_id": "s123", "turn": 1},
        )
        data = json.loads(env.model_dump_json())
        restored = EventEnvelope(**data)
        assert restored.id == env.id
        assert restored.type == env.type
        assert restored.correlation_id == env.correlation_id
        assert restored.payload == env.payload

    def test_unknown_event_type_accepted(self):
        """EventEnvelope.type is str, not locked to EventType enum."""
        from services.shared.events import EventEnvelope
        env = EventEnvelope(type="custom.vendor.event", source="external")
        assert env.type == "custom.vendor.event"

    def test_empty_payload_valid(self):
        from services.shared.events import EventEnvelope
        env = EventEnvelope(type="test.empty", source="unit")
        assert env.payload == {}
        assert env.id
        assert env.correlation_id.startswith("req_")

    def test_derive_new_id_same_correlation(self):
        from services.shared.events import EventEnvelope
        parent = EventEnvelope(
            type="parent.event",
            source="svc-a",
            correlation_id="req_fixed123456",
        )
        child = parent.derive("child.event", "svc-b", {"key": "val"})
        assert child.id != parent.id
        assert child.timestamp >= parent.timestamp
        assert child.correlation_id == "req_fixed123456"
        assert child.source == "svc-b"
        assert child.payload == {"key": "val"}

    def test_validate_accepts_valid_dict(self):
        from services.shared.events import validate_envelope
        ok, err = validate_envelope({
            "type": "test.event",
            "correlation_id": "req_abc",
            "extra": "ignored",
        })
        assert ok is True
        assert err == ""

    def test_validate_rejects_non_dict(self):
        from services.shared.events import validate_envelope
        ok, err = validate_envelope("not a dict")
        assert ok is False
        assert "dict" in err

    def test_validate_rejects_missing_correlation_key(self):
        from services.shared.events import validate_envelope
        ok, err = validate_envelope({"type": "test"})
        assert ok is False
        assert "correlation_id" in err

    def test_correlation_ids_unique(self):
        from services.shared.events import generate_correlation_id
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100

    def test_event_type_count_matches_contract(self):
        from services.shared.events import EventType
        assert len(EventType) == 24  # 19 original + 5 supervisory (v2.9)


# ===========================================================================
# DatasetManifest contract tests
# ===========================================================================

class TestManifestContract:

    def test_schema_version_is_1_1_0(self):
        from datasets.manifests.schema import SCHEMA_VERSION
        assert SCHEMA_VERSION == "1.1.0"

    def test_manifest_roundtrip_lossless(self):
        from datasets.manifests.schema import (
            DatasetManifest, Provenance, FileEntry, SplitConfig,
        )
        prov = Provenance(author="test", created_at="2026-01-01", tool_version="2.6.0")
        m = DatasetManifest(
            name="rt_test", version="1.0", source="unit", license="MIT",
            description="Roundtrip test", provenance=prov,
            files=[FileEntry(relative_path="a.jsonl", sha256="abc", size_bytes=42)],
            split_config=SplitConfig(train_ratio=0.8, val_ratio=0.1, test_ratio=0.1),
        )
        d = m.to_dict()
        m2 = DatasetManifest._from_dict(d)
        assert m2.name == m.name
        assert m2.version == m.version
        assert len(m2.files) == 1
        assert m2.files[0].sha256 == "abc"
        assert m2.split_config.train_ratio == 0.8

    def test_rejects_unknown_provenance_keys(self):
        from datasets.manifests.schema import DatasetManifest, ManifestValidationError
        data = {
            "name": "t", "version": "1", "source": "s", "license": "MIT",
            "schema_version": "1.1.0", "created_at": "2026-01-01",
            "description": "t",
            "provenance": {
                "author": "t", "created_at": "2026-01-01",
                "tool_version": "2.6.0", "ROGUE_KEY": "bad",
            },
        }
        with pytest.raises(ManifestValidationError, match="provenance"):
            DatasetManifest._from_dict(data)

    def test_validate_catches_empty_name(self):
        from datasets.manifests.schema import DatasetManifest, Provenance
        prov = Provenance(author="a", created_at="2026-01-01", tool_version="2.6.0")
        m = DatasetManifest(name="", version="1", source="s", license="MIT", provenance=prov)
        errors = m.validate()
        assert any("name" in e for e in errors)

    def test_split_config_ratios_must_sum_1(self):
        from datasets.manifests.schema import SplitConfig
        sc = SplitConfig(train_ratio=0.5, val_ratio=0.1, test_ratio=0.1)
        errors = sc.validate()
        assert any("sum" in e.lower() or "1.0" in e for e in errors)

    def test_invariant_config_bad_mode(self):
        from datasets.manifests.schema import InvariantConfig
        ic = InvariantConfig(mode="yolo")
        errors = ic.validate()
        assert any("mode" in e for e in errors)

    def test_export_config_bad_format(self):
        from datasets.manifests.schema import ExportConfig
        ec = ExportConfig(format="csv")
        errors = ec.validate()
        assert any("format" in e for e in errors)

    def test_build_id_idempotent(self):
        from datasets.manifests.schema import DatasetManifest, Provenance, FileEntry
        prov = Provenance(author="t", created_at="2026-01-01", tool_version="2.6.0")
        m = DatasetManifest(
            name="idem", version="1.0", source="s", license="MIT", provenance=prov,
            files=[FileEntry(relative_path="x.jsonl", sha256="fff", size_bytes=1)],
        )
        id1 = m.compute_build_id()
        id2 = m.compute_build_id()
        assert id1 == id2


# ===========================================================================
# SceneAnalysis contract tests
# ===========================================================================

class TestSceneAnalysisContract:

    def test_confirmation_always_true(self):
        mod = _get_perc_mod()
        sa = mod.SceneAnalysis(
            scene_id="sa1", timestamp=time.time(), trigger="user_command",
            summary="test", overall_confidence=0.5,
            action_requires_confirmation=False,
            inference_ms=10.0,
        )
        assert sa.action_requires_confirmation is True

    def test_requires_positive_timestamp(self):
        mod = _get_perc_mod()
        with pytest.raises(Exception):
            mod.SceneAnalysis(
                scene_id="sa2", timestamp=-1, trigger="user_command",
                summary="bad", overall_confidence=0.5, inference_ms=10.0,
            )

    def test_requires_nonempty_scene_id(self):
        mod = _get_perc_mod()
        with pytest.raises(Exception):
            mod.SceneAnalysis(
                scene_id="", timestamp=time.time(), trigger="user_command",
                summary="bad", overall_confidence=0.5, inference_ms=10.0,
            )

    def test_entity_confidence_bounded(self):
        mod = _get_perc_mod()
        with pytest.raises(Exception):
            mod.Entity(label="x", confidence=1.5)
        with pytest.raises(Exception):
            mod.Entity(label="x", confidence=-0.1)
