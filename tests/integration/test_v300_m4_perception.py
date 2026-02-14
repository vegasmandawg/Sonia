"""
SONIA v3.0.0 Milestone 4 -- Perception + Policy + Action Binding integration tests.

Tests:
  - Perception -> Typed Memory (7 tests)
  - Provenance Chain (4 tests)
  - Confirmation Binding (4 tests)
  - Conflict Detection (3 tests)
  - No-Bypass Enforcement (5 tests)
  - Version Chain Integration (3 tests)
  - Adversarial (2 tests)

Total: 28 tests.
Runs against in-process ASGI TestClient (no live services needed).
"""
import asyncio
import concurrent.futures
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# -- Path setup ---------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_DIR = REPO_ROOT / "services" / "shared"
GATEWAY_DIR = REPO_ROOT / "services" / "api-gateway"
MEMORY_DIR = REPO_ROOT / "services" / "memory-engine"

sys.path.insert(0, str(SHARED_DIR))
sys.path.insert(0, str(GATEWAY_DIR))
sys.path.insert(0, str(MEMORY_DIR))


def _run(coro):
    """Run an async coroutine in a dedicated thread with its own event loop.

    This avoids nested event-loop deadlocks when the coroutine internally calls
    sync code that itself enters an event loop (e.g. Starlette TestClient via anyio).
    """
    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_thread_target)
        return future.result(timeout=30)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the Memory Engine app with test DB."""
    from starlette.testclient import TestClient

    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_path = tmp_db.name

    from db import MemoryDatabase
    test_db = MemoryDatabase(db_path=tmp_path)

    sys.modules.pop("main", None)

    import db as _db_mod
    _original_get_db = _db_mod.get_db
    _db_mod.get_db = lambda: test_db

    try:
        import main as mem_main
        mem_main.db = test_db
    finally:
        _db_mod.get_db = _original_get_db

    tc = TestClient(mem_main.app, raise_server_exceptions=False)
    yield tc

    try:
        os.unlink(tmp_path)
    except OSError:
        pass


@pytest.fixture(scope="module")
def perception_gate():
    """Create a PerceptionActionGate instance for testing."""
    from perception_action_gate import PerceptionActionGate
    return PerceptionActionGate(ttl_seconds=5.0)


@pytest.fixture(scope="module")
def provenance_tracker():
    """Create a ProvenanceTracker backed by a fresh test DB."""
    from db import MemoryDatabase
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    test_db = MemoryDatabase(db_path=tmp_db.name)

    from core.provenance import ProvenanceTracker
    tracker = ProvenanceTracker(test_db)
    yield tracker

    try:
        os.unlink(tmp_db.name)
    except OSError:
        pass


@pytest.fixture
def mock_memory():
    """Create an AsyncMock memory client for bridge testing.

    Returns (mock_client, stored_memories) — stored_memories is a list
    that accumulates every store_typed call for assertion.
    """
    stored = []
    _id_counter = [0]

    mock = AsyncMock()

    async def _store_typed(memory_type="", subtype="", content="",
                           metadata=None, valid_from=None, valid_until=None,
                           correlation_id="", **kw):
        _id_counter[0] += 1
        mid = f"mock_mem_{_id_counter[0]:04d}"
        record = {
            "status": "stored", "id": mid,
            "type": memory_type, "subtype": subtype,
            "content": content, "metadata": metadata,
            "valid_from": valid_from, "valid_until": valid_until,
            "conflicts": [],
        }
        stored.append(record)
        return record

    async def _create_version(original_id="", new_content="",
                              metadata=None, valid_from=None,
                              correlation_id="", **kw):
        _id_counter[0] += 1
        vid = f"mock_ver_{_id_counter[0]:04d}"
        return {"id": vid, "original_id": original_id,
                "content": new_content, "metadata": metadata}

    mock.store_typed = AsyncMock(side_effect=_store_typed)
    mock.create_version = AsyncMock(side_effect=_create_version)
    return mock, stored


# =============================================================================
# Helpers
# =============================================================================

def _make_scene(
    scene_id="scene_001",
    timestamp="2025-06-01T12:00:00Z",
    entities=None,
    summary="Test scene summary",
    overall_confidence=0.85,
    recommended_action="",
    trigger="user_command",
    model_used="test-vlm",
    privacy_verified=True,
    action_args=None,
):
    """Build a minimal SceneAnalysis dict."""
    if entities is None:
        entities = [
            {"label": "person", "confidence": 0.9, "bounding_box": [0, 0, 100, 200],
             "attributes": {"pose": "standing"}},
            {"label": "laptop", "confidence": 0.8, "bounding_box": [50, 50, 200, 150],
             "attributes": {"state": "open"}},
        ]
    return {
        "scene_id": scene_id,
        "timestamp": timestamp,
        "entities": entities,
        "summary": summary,
        "overall_confidence": overall_confidence,
        "recommended_action": recommended_action,
        "action_requires_confirmation": True,
        "action_args": action_args or {},
        "trigger": trigger,
        "model_used": model_used,
        "privacy_verified": privacy_verified,
        "inference_ms": 150,
    }


def _store_fact(client, subject, predicate, obj, confidence=0.9,
                valid_from=None, valid_until=None):
    """Store a typed FACT via the v3 API."""
    content = json.dumps({
        "subject": subject, "predicate": predicate,
        "object": obj, "confidence": confidence,
    })
    payload = {"type": "fact", "subtype": "FACT", "content": content}
    if valid_from:
        payload["valid_from"] = valid_from
    if valid_until:
        payload["valid_until"] = valid_until
    return client.post("/v3/memory/store", json=payload)


# =============================================================================
# Group 1: Perception -> Typed Memory (7 tests)
# =============================================================================

class TestPerceptionTypedMemory:
    def test_scene_ingest_produces_facts(self, mock_memory):
        """Ingesting a scene with 2 entities produces at least 2 FACT memories."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene()
        result = _run(bridge.ingest_scene(scene, "sess_t1", "req_t1"))
        # 2 entities + 1 summary = 3 FACTs minimum
        assert len(result.memory_ids) >= 3
        assert result.entity_count == 2
        assert result.scene_id == "scene_001"

    def test_entity_extraction(self, mock_memory):
        """Each entity produces a FACT with correct subject/predicate."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(
            scene_id="scene_ent",
            entities=[{"label": "cat", "confidence": 0.95, "attributes": {"color": "orange"}}],
            summary="A cat",
        )
        result = _run(bridge.ingest_scene(scene, "sess_t2", "req_t2"))
        assert len(result.memory_ids) >= 1

        # Verify the FACT content passed to store_typed
        calls = mock_client.store_typed.call_args_list
        entity_call = [c for c in calls if "cat" in str(c)]
        assert len(entity_call) >= 1
        # Parse the content arg
        content = json.loads(entity_call[0].kwargs.get("content", entity_call[0][1][2] if len(entity_call[0][1]) > 2 else "{}"))
        assert content["subject"] == "cat"
        assert content["predicate"] == "detected_in_scene"
        assert content["object"] == "scene_ent"

    def test_summary_fact(self, mock_memory):
        """Scene summary stored as FACT with scene_id as subject."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_sum", entities=[], summary="Empty room")
        result = _run(bridge.ingest_scene(scene, "sess_t3", "req_t3"))
        assert len(result.memory_ids) == 1  # Only summary FACT (no entities)

        # Verify summary content
        last_stored = stored[-1]
        content = json.loads(last_stored["content"])
        assert content["subject"] == "scene_sum"
        assert content["predicate"] == "scene_summary"
        assert content["object"] == "Empty room"

    def test_system_state_for_action(self, mock_memory):
        """Recommended action stored as SYSTEM_STATE."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(
            scene_id="scene_act",
            entities=[],
            summary="Desk",
            recommended_action="app.launch",
        )
        result = _run(bridge.ingest_scene(scene, "sess_t4", "req_t4"))
        # Summary FACT + SYSTEM_STATE = 2 memories
        assert len(result.memory_ids) == 2

        # Last stored should be SYSTEM_STATE
        sys_state = stored[-1]
        assert sys_state["type"] == "system"
        assert sys_state["subtype"] == "SYSTEM_STATE"
        content = json.loads(sys_state["content"])
        assert content["component"] == "perception"
        assert content["state_key"] == "recommended_action"
        assert content["state_value"] == "app.launch"
        assert content["health_status"] == "pending_confirmation"

    def test_temporal_fields_correct(self, mock_memory):
        """valid_from should equal scene timestamp."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(
            scene_id="scene_temp",
            timestamp="2025-03-15T10:30:00Z",
            entities=[{"label": "book", "confidence": 0.7}],
            summary="A book",
        )
        result = _run(bridge.ingest_scene(scene, "sess_t5", "req_t5"))
        assert len(result.memory_ids) >= 1

        # Check valid_from in store_typed calls
        for call in mock_client.store_typed.call_args_list[-2:]:
            kwargs = call.kwargs
            assert kwargs.get("valid_from") == "2025-03-15T10:30:00Z"

    def test_metadata_shape(self, mock_memory):
        """Metadata includes required perception fields."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_meta", entities=[], summary="Test")
        result = _run(bridge.ingest_scene(scene, "sess_t6", "req_t6"))
        assert len(result.memory_ids) >= 1

        last = stored[-1]
        meta = last["metadata"]
        assert meta["scene_id"] == "scene_meta"
        assert meta["source_type"] == "perception"
        assert meta["correlation_id"] == "req_t6"
        assert meta["trigger"] == "user_command"
        assert meta["model_used"] == "test-vlm"

    def test_correlation_id_propagated(self, mock_memory):
        """Correlation ID should appear in result."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_corr", entities=[], summary="Corr test")
        result = _run(bridge.ingest_scene(scene, "sess_t7", "req_t7_unique"))
        assert result.correlation_id == "req_t7_unique"


# =============================================================================
# Group 2: Provenance Chain (4 tests)
# =============================================================================

class TestProvenanceChain:
    def test_track_provenance_endpoint(self, client):
        """POST /v1/provenance/track should succeed."""
        r = _store_fact(client, "ProvTest", "has", "provenance")
        mid = r.json()["id"]

        r2 = client.post("/v1/provenance/track", json={
            "memory_id": mid,
            "source_type": "perception",
            "source_id": "scene_prov",
            "metadata": {"trigger": "user_command", "model_used": "vlm-1"},
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "tracked"

    def test_provenance_chain_links_scene(self, client):
        """Provenance chain should link back to scene_id."""
        r = _store_fact(client, "ChainTest", "from", "perception")
        mid = r.json()["id"]

        client.post("/v1/provenance/track", json={
            "memory_id": mid,
            "source_type": "perception",
            "source_id": "scene_chain_01",
        })

        r2 = client.get(f"/v1/provenance/{mid}")
        assert r2.status_code == 200
        prov = r2.json()["provenance"]
        assert prov["source_type"] == "perception"
        assert prov["source_id"] == "scene_chain_01"

    def test_track_perception_validates_fields(self, provenance_tracker):
        """track_perception() should reject empty required fields."""
        with pytest.raises(ValueError, match="scene_id"):
            provenance_tracker.track_perception(
                "mem_test", scene_id="", correlation_id="req_1",
                trigger="test", model_used="vlm",
            )
        with pytest.raises(ValueError, match="model_used"):
            provenance_tracker.track_perception(
                "mem_test", scene_id="s1", correlation_id="req_1",
                trigger="test", model_used="",
            )

    def test_track_perception_succeeds(self, provenance_tracker):
        """track_perception() should store with correct source_type."""
        provenance_tracker.track_perception(
            "mem_prov_ok", scene_id="scene_99", correlation_id="req_99",
            trigger="wake_word", model_used="vlm-2",
        )
        record = provenance_tracker.get_provenance("mem_prov_ok")
        assert record["source_type"] == "perception"
        assert record["source_id"] == "scene_99"
        assert record["metadata"]["trigger"] == "wake_word"
        assert record["metadata"]["model_used"] == "vlm-2"


# =============================================================================
# Group 3: Confirmation Binding (4 tests)
# =============================================================================

class TestConfirmationBinding:
    def test_action_gated(self, mock_memory):
        """bind_action_confirmation creates a pending confirmation."""
        from perception_memory_bridge import PerceptionMemoryBridge
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate(ttl_seconds=30.0)
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_gate", recommended_action="shell.run",
                            entities=[], summary="Gate test")
        req = _run(bridge.bind_action_confirmation(scene, gate, "sess_g1", "req_g1"))
        assert req is not None
        assert req.is_pending
        assert req.action == "shell.run"
        assert req.scene_id == "scene_gate"

    def test_system_state_records_pending(self, mock_memory):
        """Confirmation binding writes SYSTEM_STATE with pending status."""
        from perception_memory_bridge import PerceptionMemoryBridge
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate(ttl_seconds=30.0)
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_pend", recommended_action="file.write",
                            entities=[], summary="Pend test")
        req = _run(bridge.bind_action_confirmation(scene, gate, "sess_g2", "req_g2"))
        # The confirmation memory should exist
        conf_mid = getattr(req, "confirmation_memory_id", None)
        assert conf_mid is not None

        # Verify SYSTEM_STATE was stored
        sys_calls = [s for s in stored if s["subtype"] == "SYSTEM_STATE"
                     and "confirmation:" in s["content"]]
        assert len(sys_calls) >= 1
        content = json.loads(sys_calls[-1]["content"])
        assert content["state_value"] == "pending"
        assert content["component"] == "perception_gate"

    def test_approval_creates_version(self, mock_memory):
        """Approving a confirmation creates a new version of the SYSTEM_STATE."""
        from perception_memory_bridge import PerceptionMemoryBridge
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate(ttl_seconds=30.0)
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_appr", recommended_action="browser.open",
                            entities=[], summary="Approval test")
        req = _run(bridge.bind_action_confirmation(scene, gate, "sess_g3", "req_g3"))
        gate.approve(req.requirement_id)

        new_vid = _run(bridge.on_confirmation_resolved(req, "approved", "req_g3"))
        assert new_vid is not None

        # create_version was called
        mock_client.create_version.assert_called()
        last_call = mock_client.create_version.call_args
        new_content = json.loads(last_call.kwargs.get("new_content",
                                                       last_call[1].get("new_content", "{}")))
        assert new_content["state_value"] == "approved"
        assert new_content["health_status"] == "resolved"

    def test_denial_creates_version(self, mock_memory):
        """Denying a confirmation creates a version with denied status."""
        from perception_memory_bridge import PerceptionMemoryBridge
        from perception_action_gate import PerceptionActionGate
        gate = PerceptionActionGate(ttl_seconds=30.0)
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_deny", recommended_action="keyboard.type",
                            entities=[], summary="Denial test")
        req = _run(bridge.bind_action_confirmation(scene, gate, "sess_g4", "req_g4"))
        gate.deny(req.requirement_id, reason="unsafe")

        new_vid = _run(bridge.on_confirmation_resolved(req, "denied", "req_g4"))
        assert new_vid is not None

        last_call = mock_client.create_version.call_args
        new_content = json.loads(last_call.kwargs.get("new_content",
                                                       last_call[1].get("new_content", "{}")))
        assert new_content["state_value"] == "denied"


# =============================================================================
# Group 4: Conflict Detection (3 tests) — uses real TestClient
# =============================================================================

class TestConflictDetection:
    def test_contradicting_observations(self, client):
        """Same entity with different object -> FACT conflict."""
        # First observation
        _store_fact(client, "door_conflict_m4", "detected_in_scene", "scene_c1", 0.9)
        # Second observation: same (subject, predicate) but different object
        r2 = _store_fact(client, "door_conflict_m4", "detected_in_scene", "scene_c2", 0.9)
        assert r2.status_code == 200
        assert len(r2.json()["conflicts"]) >= 1

    def test_same_entity_same_state_no_conflict(self, client):
        """Same (subject, predicate, object) -> no conflict."""
        _store_fact(client, "noconflict_m4", "detected_in_scene", "scene_nc1", 0.9)
        r2 = _store_fact(client, "noconflict_m4", "detected_in_scene", "scene_nc1", 0.9)
        assert r2.status_code == 200
        assert len(r2.json()["conflicts"]) == 0

    def test_temporal_overlap_detected(self, client):
        """Overlapping temporal observations of conflicting facts."""
        _store_fact(client, "overlap_m4", "state_is", "active",
                    valid_from="2025-01-01T00:00:00Z", valid_until="2025-12-01T00:00:00Z")
        r2 = _store_fact(client, "overlap_m4", "state_is", "inactive",
                         valid_from="2025-06-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
        assert r2.status_code == 200
        assert len(r2.json()["conflicts"]) >= 1


# =============================================================================
# Group 5: No-Bypass Enforcement (5 tests) — pure gate logic, no DB
# =============================================================================

class TestNoBypassEnforcement:
    def test_direct_execute_without_gate_raises(self):
        """validate_execution on unknown requirement -> ConfirmationBypassError."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate()

        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution("nonexistent_req")

    def test_expired_requirement_rejected(self):
        """Expired requirements cannot be validated."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate(ttl_seconds=0.01)

        req = gate.require_confirmation(action="file.read", scene_id="scene_exp")
        time.sleep(0.05)

        with pytest.raises(ConfirmationBypassError, match="expired"):
            gate.validate_execution(req.requirement_id)

    def test_double_execute_rejected(self):
        """One-shot: second validate_execution raises."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate(ttl_seconds=30.0)

        req = gate.require_confirmation(action="file.read", scene_id="scene_dbl")
        gate.approve(req.requirement_id)
        gate.validate_execution(req.requirement_id)  # First: OK

        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution(req.requirement_id)  # Second: error

    def test_denied_requirement_rejected(self):
        """Denied requirements cannot be validated."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate(ttl_seconds=30.0)

        req = gate.require_confirmation(action="shell.run", scene_id="scene_den")
        gate.deny(req.requirement_id, reason="test")

        with pytest.raises(ConfirmationBypassError, match="not approved"):
            gate.validate_execution(req.requirement_id)

    def test_unapproved_validate_execution_raises(self):
        """Pending (unapproved) requirements cannot be validated."""
        from perception_action_gate import PerceptionActionGate, ConfirmationBypassError
        gate = PerceptionActionGate(ttl_seconds=30.0)

        req = gate.require_confirmation(action="app.launch", scene_id="scene_unap")

        with pytest.raises(ConfirmationBypassError, match="pending"):
            gate.validate_execution(req.requirement_id)


# =============================================================================
# Group 6: Version Chain Integration (3 tests) — uses real TestClient
# =============================================================================

class TestVersionChainIntegration:
    def test_scene_supersedes_prior_observation(self, client):
        """A new observation can supersede a prior one via create_version."""
        r1 = _store_fact(client, "supersede_m4", "position", "left_side")
        orig_id = r1.json()["id"]

        new_content = json.dumps({
            "subject": "supersede_m4", "predicate": "position",
            "object": "right_side", "confidence": 0.95,
        })
        r2 = client.post("/v3/memory/version", json={
            "original_id": orig_id, "new_content": new_content,
        })
        assert r2.status_code == 200

        r3 = client.get(f"/v3/memory/{orig_id}/versions")
        versions = r3.json()["versions"]
        assert len(versions) == 2

    def test_version_history_preserves_chain_head(self, client):
        """All versions in chain share the same version_chain_head."""
        r1 = _store_fact(client, "chain_head_m4", "obs", "v1")
        orig_id = r1.json()["id"]

        new_content = json.dumps({
            "subject": "chain_head_m4", "predicate": "obs",
            "object": "v2", "confidence": 0.9,
        })
        client.post("/v3/memory/version", json={
            "original_id": orig_id, "new_content": new_content,
        })

        r3 = client.get(f"/v3/memory/{orig_id}/versions")
        versions = r3.json()["versions"]
        heads = set(v["version_chain_head"] for v in versions)
        assert len(heads) == 1
        assert orig_id in heads

    def test_chain_head_stable_across_versions(self, client):
        """Chain head self-ref preserved after multiple versions."""
        r1 = _store_fact(client, "stable_head_m4", "test", "v1")
        orig_id = r1.json()["id"]

        for i in range(2, 5):
            r = client.get(f"/v3/memory/{orig_id}/versions")
            versions = r.json()["versions"]
            current = [v for v in versions if v["superseded_by"] is None][0]
            new_content = json.dumps({
                "subject": "stable_head_m4", "predicate": "test",
                "object": f"v{i}", "confidence": 0.9,
            })
            client.post("/v3/memory/version", json={
                "original_id": current["id"], "new_content": new_content,
            })

        r_final = client.get(f"/v3/memory/{orig_id}/versions")
        versions = r_final.json()["versions"]
        assert len(versions) == 4
        for v in versions:
            assert v["version_chain_head"] == orig_id


# =============================================================================
# Group 7: Adversarial (2 tests)
# =============================================================================

class TestAdversarial:
    def test_invalid_scene_rejected_gracefully(self, mock_memory):
        """Missing scene_id should return error, not crash."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = {"entities": [], "summary": "No scene_id"}
        result = _run(bridge.ingest_scene(scene, "sess_adv1", "req_adv1"))
        assert len(result.errors) >= 1
        assert "scene_id" in result.errors[0].lower()
        assert len(result.memory_ids) == 0

    def test_empty_entities_handled(self, mock_memory):
        """Scene with no entities should still produce summary FACT."""
        from perception_memory_bridge import PerceptionMemoryBridge
        mock_client, stored = mock_memory
        bridge = PerceptionMemoryBridge(mock_client)

        scene = _make_scene(scene_id="scene_empty", entities=[], summary="Empty scene")
        result = _run(bridge.ingest_scene(scene, "sess_adv2", "req_adv2"))
        assert result.entity_count == 0
        assert len(result.memory_ids) >= 1
        assert len(result.errors) == 0
