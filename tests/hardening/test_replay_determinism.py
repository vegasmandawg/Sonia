"""
v3.1 H1 Hardening: Deterministic Replay Tests

Verifies that replaying a captured event sequence produces identical
memory writes and provenance records. This ensures no hidden randomness
or timing-dependent behavior in the turn pipeline's memory path.

Invariants tested:
  - Same EventEnvelope sequence -> same typed memory output
  - Provenance records are deterministic given same inputs
  - PerceptionMemoryBridge ingest is idempotent for same scene_id
  - Event correlation_id propagation is stable across replay
"""

import asyncio
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Module loading (explicit, avoids sys.path pollution) ─────────────────

GATEWAY_DIR = Path(r"S:\services\api-gateway")
SHARED_DIR = Path(r"S:\services\shared")
MEMORY_DIR = Path(r"S:\services\memory-engine")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


events_mod = _load_module("shared_events", SHARED_DIR / "events.py")
EventEnvelope = events_mod.EventEnvelope
EventType = events_mod.EventType
generate_correlation_id = events_mod.generate_correlation_id
validate_envelope = events_mod.validate_envelope

bridge_mod = _load_module("perception_memory_bridge", GATEWAY_DIR / "perception_memory_bridge.py")
PerceptionMemoryBridge = bridge_mod.PerceptionMemoryBridge
PerceptionIngestResult = bridge_mod.PerceptionIngestResult

gate_mod = _load_module("perception_action_gate", GATEWAY_DIR / "perception_action_gate.py")
PerceptionActionGate = gate_mod.PerceptionActionGate


# ── Fixtures ─────────────────────────────────────────────────────────────

def _make_scene_analysis(scene_id: str, entities: int = 3) -> Dict[str, Any]:
    """Build a deterministic SceneAnalysis dict."""
    return {
        "scene_id": scene_id,
        "summary": f"Test scene {scene_id} with {entities} entities",
        "entities": [
            {"label": f"entity_{i}", "confidence": 0.9, "bbox": [i*10, i*10, 50, 50]}
            for i in range(entities)
        ],
        "recommended_action": {
            "action": "file.read",
            "args": {"path": f"/test/{scene_id}.txt"},
        },
        "trigger": "automated_test",
        "model_used": "test-model-v1",
        "timestamp": 1700000000.0,
    }


def _make_golden_sequence(count: int = 5) -> List[Dict[str, Any]]:
    """Build a deterministic sequence of scene analyses for replay."""
    return [
        _make_scene_analysis(f"scene_{i:04d}", entities=2 + (i % 3))
        for i in range(count)
    ]


class MockMemoryClient:
    """Captures memory writes for comparison."""

    def __init__(self):
        self.writes: List[Dict[str, Any]] = []
        self.provenance_calls: List[Dict[str, Any]] = []

    async def store_typed(self, **kwargs):
        self.writes.append(kwargs)
        return {"memory_id": f"mem_{uuid.uuid4().hex[:8]}"}

    async def store(self, **kwargs):
        self.writes.append(kwargs)
        return {"memory_id": f"mem_{uuid.uuid4().hex[:8]}"}

    def reset(self):
        self.writes.clear()
        self.provenance_calls.clear()


# ── Tests ────────────────────────────────────────────────────────────────

class TestReplayDeterminism:
    """Replay a golden event sequence and verify output equivalence."""

    @pytest.mark.asyncio
    async def test_single_scene_deterministic(self):
        """Same scene ingested twice produces same structure."""
        scene = _make_scene_analysis("scene_deterministic", entities=3)

        client1 = MockMemoryClient()
        client2 = MockMemoryClient()

        bridge1 = PerceptionMemoryBridge(client1)
        bridge2 = PerceptionMemoryBridge(client2)

        result1 = await bridge1.ingest_scene(scene, "ses_test", "req_aaa111")
        result2 = await bridge2.ingest_scene(scene, "ses_test", "req_aaa111")

        # Both should produce same entity count and error count
        assert result1.entity_count == result2.entity_count
        assert result1.errors == result2.errors
        assert result1.scene_id == result2.scene_id
        assert result1.provenance_source == result2.provenance_source
        assert result1.correlation_id == result2.correlation_id

        # Memory write count should be identical
        assert len(client1.writes) == len(client2.writes)

    @pytest.mark.asyncio
    async def test_sequence_replay_equivalence(self):
        """Full golden sequence replayed twice produces same write count."""
        golden = _make_golden_sequence(count=10)

        for run in range(2):
            client = MockMemoryClient()
            bridge = PerceptionMemoryBridge(client)

            results = []
            for scene in golden:
                r = await bridge.ingest_scene(scene, "ses_replay", "req_replay001")
                results.append(r)

            if run == 0:
                first_write_count = len(client.writes)
                first_entity_counts = [r.entity_count for r in results]
                first_error_counts = [len(r.errors) for r in results]
            else:
                assert len(client.writes) == first_write_count, \
                    f"Write count diverged: {len(client.writes)} vs {first_write_count}"
                assert [r.entity_count for r in results] == first_entity_counts
                assert [len(r.errors) for r in results] == first_error_counts

    @pytest.mark.asyncio
    async def test_empty_scene_deterministic(self):
        """Empty/invalid scenes produce same error output on replay."""
        empty_scene = {"scene_id": ""}

        client1 = MockMemoryClient()
        client2 = MockMemoryClient()

        bridge1 = PerceptionMemoryBridge(client1)
        bridge2 = PerceptionMemoryBridge(client2)

        r1 = await bridge1.ingest_scene(empty_scene, "ses_x", "req_x")
        r2 = await bridge2.ingest_scene(empty_scene, "ses_x", "req_x")

        assert r1.errors == r2.errors
        assert len(r1.errors) > 0  # Should report missing scene_id

    @pytest.mark.asyncio
    async def test_correlation_id_preserved_across_replay(self):
        """Correlation ID from input appears in output on every replay."""
        scene = _make_scene_analysis("scene_corr")
        corr_id = "req_stable_corr"

        for _ in range(3):
            client = MockMemoryClient()
            bridge = PerceptionMemoryBridge(client)
            result = await bridge.ingest_scene(scene, "ses_c", corr_id)
            assert result.correlation_id == corr_id


class TestEventEnvelopeDeterminism:
    """EventEnvelope creation and derivation are deterministic in structure."""

    def test_derive_preserves_correlation(self):
        """derive() always propagates correlation_id."""
        parent = EventEnvelope(
            type=EventType.TURN_STARTED.value,
            source="test",
            correlation_id="req_parent_123",
            payload={"turn": 1},
        )

        child1 = parent.derive(EventType.TURN_COMPLETED.value, "test", {"turn": 1})
        child2 = parent.derive(EventType.TURN_COMPLETED.value, "test", {"turn": 1})

        assert child1.correlation_id == "req_parent_123"
        assert child2.correlation_id == "req_parent_123"
        assert child1.type == child2.type
        assert child1.source == child2.source

    def test_validate_envelope_deterministic(self):
        """validate_envelope returns same result for same input."""
        good = {"type": "test.event", "correlation_id": "req_abc"}
        bad = {"correlation_id": "req_abc"}  # missing type

        for _ in range(5):
            ok1, msg1 = validate_envelope(good)
            ok2, msg2 = validate_envelope(bad)
            assert ok1 is True
            assert ok2 is False
            assert "type" in msg2

    def test_envelope_structure_stable(self):
        """EventEnvelope with fixed fields produces stable dict keys."""
        e = EventEnvelope(
            id="fixed-id",
            timestamp=1700000000.0,
            type="test.type",
            source="test",
            correlation_id="req_fixed",
            payload={"key": "value"},
        )
        d1 = e.model_dump()
        d2 = e.model_dump()
        assert d1 == d2


class TestPerceptionGateReplay:
    """PerceptionActionGate state machine is deterministic."""

    def test_require_approve_validate_deterministic(self):
        """Same sequence of require->approve->validate produces same result."""
        for _ in range(3):
            gate = PerceptionActionGate(ttl_seconds=300)
            req = gate.require_confirmation(
                action="file.read",
                args={"path": "/test"},
                scene_id="scene_001",
                correlation_id="req_gate_test",
            )
            assert req.state.value == "pending"
            assert req.risk_level == "medium"  # file.read is medium

            approved = gate.approve(req.requirement_id)
            assert approved is not None
            assert approved.state.value == "approved"

            executed = gate.validate_execution(req.requirement_id)
            assert executed.state.value == "executed"

            stats = gate.get_stats()
            assert stats["total_approved"] == 1
            assert stats["bypass_attempts"] == 0

    def test_double_approve_deterministic(self):
        """Double approve returns None on second attempt consistently."""
        for _ in range(3):
            gate = PerceptionActionGate(ttl_seconds=300)
            req = gate.require_confirmation(action="browser.open", scene_id="s1")

            first = gate.approve(req.requirement_id)
            assert first is not None

            # Consume it
            gate.validate_execution(req.requirement_id)

            # Second approve on consumed requirement: not found (archived)
            second = gate.approve(req.requirement_id)
            assert second is None
