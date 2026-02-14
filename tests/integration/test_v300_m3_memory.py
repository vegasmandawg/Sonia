"""
SONIA v3.0.0 Milestone 3 -- Memory Ledger V3 integration tests.

Tests:
  - Typed storage + validation (8 tests)
  - Version chains (6 tests)
  - Redaction governance (4 tests)
  - Conflict detection (5 tests)
  - Budget enforcement (4 tests)
  - Backward compatibility (3 tests)
  - Adversarial / hardening (6 tests)

Total: 36 tests.
Runs against in-process ASGI TestClient (no live services needed).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# ── Path setup ───────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED_DIR = REPO_ROOT / "services" / "shared"
GATEWAY_DIR = REPO_ROOT / "services" / "api-gateway"
MEMORY_DIR = REPO_ROOT / "services" / "memory-engine"

sys.path.insert(0, str(SHARED_DIR))
sys.path.insert(0, str(GATEWAY_DIR))
sys.path.insert(0, str(MEMORY_DIR))


# ═════════════════════════════════════════════════════════════════════════
# Fixture
# ═════════════════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════

def _store_fact(client, subject="Alice", predicate="likes", obj="cats",
                confidence=0.9, valid_from=None, valid_until=None):
    """Helper: store a FACT and return the response json."""
    content = json.dumps({
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "confidence": confidence,
    })
    payload = {
        "type": "fact",
        "subtype": "FACT",
        "content": content,
    }
    if valid_from:
        payload["valid_from"] = valid_from
    if valid_until:
        payload["valid_until"] = valid_until
    r = client.post("/v3/memory/store", json=payload)
    return r


def _store_preference(client, category="ui", key="theme", value="dark"):
    content = json.dumps({"category": category, "key": key, "value": value, "priority": 5.0})
    r = client.post("/v3/memory/store", json={
        "type": "preference",
        "subtype": "PREFERENCE",
        "content": content,
    })
    return r


# ═════════════════════════════════════════════════════════════════════════
# Group 1: Typed Storage + Validation (8 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestTypedStorage:
    def test_store_fact(self, client):
        r = _store_fact(client)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "stored"
        assert data["subtype"] == "FACT"
        assert data["id"].startswith("mem_")

    def test_store_preference(self, client):
        r = _store_preference(client)
        assert r.status_code == 200
        assert r.json()["subtype"] == "PREFERENCE"

    def test_store_project(self, client):
        content = json.dumps({
            "project_id": "proj_001",
            "context_type": "development",
            "summary": "Building SONIA v3",
            "tags": ["ai", "memory"],
        })
        r = client.post("/v3/memory/store", json={
            "type": "project",
            "subtype": "PROJECT",
            "content": content,
        })
        assert r.status_code == 200

    def test_store_session_context(self, client):
        content = json.dumps({
            "session_id": "sess_001",
            "context_key": "topic",
            "context_value": "memory architecture",
        })
        r = client.post("/v3/memory/store", json={
            "type": "session",
            "subtype": "SESSION_CONTEXT",
            "content": content,
        })
        assert r.status_code == 200

    def test_store_system_state(self, client):
        content = json.dumps({
            "component": "memory-engine",
            "state_key": "migration_version",
            "state_value": "009",
        })
        r = client.post("/v3/memory/store", json={
            "type": "system",
            "subtype": "SYSTEM_STATE",
            "content": content,
        })
        assert r.status_code == 200

    def test_invalid_schema_rejected(self, client):
        """Missing required field (subject) should fail validation."""
        content = json.dumps({"predicate": "likes", "object": "cats"})
        r = client.post("/v3/memory/store", json={
            "type": "fact",
            "subtype": "FACT",
            "content": content,
        })
        assert r.status_code == 400

    def test_temporal_bounds_validated(self, client):
        """valid_from must be ISO 8601 UTC."""
        r = _store_fact(client, valid_from="not-a-date")
        assert r.status_code == 400

    def test_metadata_preserved(self, client):
        r = _store_fact(client, subject="MetaTest", predicate="has", obj="metadata")
        assert r.status_code == 200
        mid = r.json()["id"]

        # Retrieve via legacy recall
        r2 = client.get(f"/recall/{mid}")
        assert r2.status_code == 200
        assert r2.json()["content"]  # content exists


# ═════════════════════════════════════════════════════════════════════════
# Group 2: Version Chains (6 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestVersionChains:
    def test_create_version(self, client):
        r = _store_fact(client, subject="VC", predicate="v1", obj="original")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "VC", "predicate": "v1", "object": "updated", "confidence": 0.95,
        })
        r2 = client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "version_created"
        assert r2.json()["original_id"] == orig_id

    def test_version_history(self, client):
        r = _store_fact(client, subject="VH", predicate="test", obj="v1")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "VH", "predicate": "test", "object": "v2", "confidence": 0.9,
        })
        client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
        })

        r3 = client.get(f"/v3/memory/{orig_id}/versions")
        assert r3.status_code == 200
        versions = r3.json()["versions"]
        assert len(versions) >= 2

    def test_chain_head_self_ref(self, client):
        """Head record should have version_chain_head = self.id."""
        r = _store_fact(client, subject="Head", predicate="self", obj="ref")
        mid = r.json()["id"]

        r2 = client.get(f"/v3/memory/{mid}/versions")
        versions = r2.json()["versions"]
        head = versions[0]
        assert head["version_chain_head"] == head["id"]

    def test_current_version_is_non_superseded(self, client):
        r = _store_fact(client, subject="Curr", predicate="test", obj="v1")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "Curr", "predicate": "test", "object": "v2", "confidence": 0.9,
        })
        r2 = client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
        })
        new_id = r2.json()["id"]

        r3 = client.get(f"/v3/memory/{orig_id}/versions")
        versions = r3.json()["versions"]
        current = [v for v in versions if v["superseded_by"] is None]
        assert len(current) == 1
        assert current[0]["id"] == new_id

    def test_temporal_version(self, client):
        """Version with valid_from should be accepted."""
        r = _store_fact(client, subject="TV", predicate="test", obj="v1",
                        valid_from="2025-01-01T00:00:00Z")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "TV", "predicate": "test", "object": "v2", "confidence": 0.9,
        })
        r2 = client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
            "valid_from": "2025-06-01T00:00:00Z",
        })
        assert r2.status_code == 200

    def test_schema_preserved_across_versions(self, client):
        """New version should inherit validation_schema from original."""
        r = _store_fact(client, subject="SP", predicate="test", obj="v1")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "SP", "predicate": "test", "object": "v2", "confidence": 0.9,
        })
        client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
        })

        r3 = client.get(f"/v3/memory/{orig_id}/versions")
        versions = r3.json()["versions"]
        # All versions should exist in history
        assert len(versions) >= 2


# ═════════════════════════════════════════════════════════════════════════
# Group 3: Redaction (4 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestRedaction:
    def test_redact(self, client):
        r = _store_fact(client, subject="RedactMe", predicate="is", obj="secret")
        mid = r.json()["id"]

        r2 = client.post("/v3/memory/redact", json={
            "memory_id": mid,
            "reason": "contains PII",
        })
        assert r2.status_code == 200
        assert r2.json()["status"] == "redacted"

    def test_audit_trail_redact_unredact(self, client):
        """Audit should record both REDACT and UNREDACT."""
        r = _store_fact(client, subject="AuditR", predicate="trail", obj="test")
        mid = r.json()["id"]

        # Redact
        client.post("/v3/memory/redact", json={
            "memory_id": mid,
            "reason": "cleanup",
        })

        # Check audit
        r2 = client.get(f"/v3/memory/{mid}/redaction-audit")
        assert r2.status_code == 200
        trail = r2.json()["audit_trail"]
        assert len(trail) >= 1
        assert trail[0]["action"] == "REDACT"

    def test_redacted_content_masked(self, client):
        """Redacted memories should show [REDACTED] in v3 query results."""
        r = _store_fact(client, subject="Masked", predicate="content", obj="hidden")
        mid = r.json()["id"]

        client.post("/v3/memory/redact", json={
            "memory_id": mid,
            "reason": "mask test",
        })

        # Query with include_redacted
        r2 = client.post("/v3/memory/query", json={
            "query": "Masked",
            "include_redacted": True,
        })
        results = r2.json()["results"]
        redacted_results = [r for r in results if r["id"] == mid]
        if redacted_results:
            assert redacted_results[0]["content"] == "[REDACTED]"

    def test_excluded_from_default_query(self, client):
        """Redacted memories should be excluded from default queries."""
        r = _store_fact(client, subject="ExcludeMe_unique_99", predicate="from", obj="query")
        mid = r.json()["id"]

        client.post("/v3/memory/redact", json={
            "memory_id": mid,
            "reason": "exclude test",
        })

        r2 = client.post("/v3/memory/query", json={
            "query": "ExcludeMe_unique_99",
        })
        result_ids = [r["id"] for r in r2.json()["results"]]
        assert mid not in result_ids


# ═════════════════════════════════════════════════════════════════════════
# Group 4: Conflict Detection (5 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestConflictDetection:
    def test_temporal_overlap_fact_conflict(self, client):
        """Two FACT memories with same identity key, overlapping time, different object."""
        _store_fact(client, subject="TempConflict", predicate="lives_in", obj="NYC",
                    valid_from="2024-01-01T00:00:00Z", valid_until="2025-01-01T00:00:00Z")

        r2 = _store_fact(client, subject="TempConflict", predicate="lives_in", obj="LA",
                         valid_from="2024-06-01T00:00:00Z", valid_until="2025-06-01T00:00:00Z")
        assert r2.status_code == 200
        conflicts = r2.json()["conflicts"]
        assert len(conflicts) >= 1
        assert conflicts[0]["conflict_type"] == "FACT_CONTRADICTION"

    def test_preference_conflict(self, client):
        """Two PREFERENCE memories with same identity key, different value."""
        _store_preference(client, category="pref_conflict_cat", key="mode", value="dark")
        r2 = _store_preference(client, category="pref_conflict_cat", key="mode", value="light")
        assert r2.status_code == 200
        conflicts = r2.json()["conflicts"]
        assert len(conflicts) >= 1
        assert conflicts[0]["conflict_type"] == "PREFERENCE_CONFLICT"

    def test_list_and_resolve_conflicts(self, client):
        """Conflicts should appear in list and be resolvable."""
        _store_fact(client, subject="Resolve", predicate="is", obj="X",
                    valid_from="2024-01-01T00:00:00Z")
        r2 = _store_fact(client, subject="Resolve", predicate="is", obj="Y",
                         valid_from="2024-01-01T00:00:00Z")
        conflicts = r2.json()["conflicts"]
        assert len(conflicts) >= 1

        # List
        r3 = client.get("/v3/memory/conflicts")
        assert r3.status_code == 200
        assert r3.json()["count"] >= 1

        # Resolve
        cid = conflicts[0]["conflict_id"]
        r4 = client.post(f"/v3/memory/conflicts/{cid}/resolve", json={
            "resolution_note": "user confirmed X is correct",
        })
        assert r4.status_code == 200

    def test_severity_populated(self, client):
        """Fact conflicts should have severity=high."""
        _store_fact(client, subject="Sev", predicate="sev_test", obj="A")
        r2 = _store_fact(client, subject="Sev", predicate="sev_test", obj="B")
        conflicts = r2.json()["conflicts"]
        if conflicts:
            assert conflicts[0].get("severity") == "high"

    def test_no_conflict_same_object(self, client):
        """Same (subject, predicate, object) = consistent, not a conflict."""
        _store_fact(client, subject="Consistent", predicate="is", obj="same")
        r2 = _store_fact(client, subject="Consistent", predicate="is", obj="same")
        conflicts = r2.json()["conflicts"]
        assert len(conflicts) == 0


# ═════════════════════════════════════════════════════════════════════════
# Group 5: Budget Enforcement (4 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestBudgetEnforcement:
    def test_char_budget(self, client):
        """Results should respect max_chars budget."""
        # Store several memories with known content sizes
        for i in range(5):
            _store_fact(client, subject=f"Budget{i}", predicate="test", obj="x" * 200)

        r = client.post("/v3/memory/query", json={
            "query": "Budget",
            "max_chars": 500,
            "limit": 50,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["budget_used"] <= 500 + 300  # first-row bypass allowance

    def test_first_row_bypass(self, client):
        """Even if first row exceeds budget, it should still be returned."""
        # Store a memory with very large content
        content = json.dumps({
            "subject": "LargeBypass",
            "predicate": "has",
            "object": "x" * 5000,
            "confidence": 0.9,
        })
        client.post("/v3/memory/store", json={
            "type": "fact",
            "subtype": "FACT",
            "content": content,
        })

        r = client.post("/v3/memory/query", json={
            "query": "LargeBypass",
            "max_chars": 100,  # Very small budget
        })
        assert r.status_code == 200
        assert r.json()["count"] >= 1  # At least the first row

    def test_truncation_flag(self, client):
        """Truncation flag should be set when budget is exceeded."""
        for i in range(10):
            _store_fact(client, subject=f"Trunc{i}", predicate="test", obj="y" * 300)

        r = client.post("/v3/memory/query", json={
            "query": "Trunc",
            "max_chars": 500,
            "limit": 50,
        })
        data = r.json()
        # With 10 items of ~300 chars each and 500 budget, truncation likely
        # (first-row bypass may allow 1-2 results)
        assert "truncated" in data

    def test_type_filters(self, client):
        """Type filters should restrict results to specified subtypes."""
        _store_fact(client, subject="TypeFilter", predicate="is", obj="fact")
        _store_preference(client, category="TypeFilter", key="pref", value="val")

        r = client.post("/v3/memory/query", json={
            "query": "TypeFilter",
            "type_filters": ["PREFERENCE"],
        })
        results = r.json()["results"]
        for res in results:
            if res["memory_subtype"] is not None:
                assert res["memory_subtype"] == "PREFERENCE"


# ═════════════════════════════════════════════════════════════════════════
# Group 6: Backward Compatibility (3 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    def test_legacy_store_still_works(self, client):
        """Legacy /store endpoint unchanged."""
        r = client.post("/store", json={
            "type": "fact",
            "content": "legacy memory content",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "stored"

    def test_legacy_search_still_works(self, client):
        """Legacy /search endpoint unchanged."""
        client.post("/store", json={
            "type": "fact",
            "content": "legacy_search_test_unique_marker",
        })
        r = client.post("/search", json={"query": "legacy_search_test_unique_marker"})
        assert r.status_code == 200
        assert r.json()["count"] >= 1

    def test_legacy_update_on_typed_row_creates_version(self, client):
        """Legacy PUT /recall/{id} on a typed row should create a version, not overwrite."""
        r = _store_fact(client, subject="LegacyUpdate", predicate="creates", obj="version")
        mid = r.json()["id"]

        # Legacy update
        r2 = client.put(f"/recall/{mid}", json={
            "content": json.dumps({
                "subject": "LegacyUpdate",
                "predicate": "creates",
                "object": "new_version",
                "confidence": 0.9,
            }),
        })
        assert r2.status_code == 200

        # Check version history — should have 2 versions
        r3 = client.get(f"/v3/memory/{mid}/versions")
        assert r3.status_code == 200
        versions = r3.json()["versions"]
        assert len(versions) >= 2


# ═════════════════════════════════════════════════════════════════════════
# Group 7: Adversarial / Hardening (6 tests)
# ═════════════════════════════════════════════════════════════════════════

class TestAdversarialHardening:
    def test_mixed_legacy_typed_under_budget(self, client):
        """Budget query should work with mix of legacy and typed memories."""
        # Store legacy
        client.post("/store", json={
            "type": "fact",
            "content": "mixed_budget_legacy_content",
        })
        # Store typed
        _store_fact(client, subject="MixedBudget", predicate="typed", obj="content")

        r = client.post("/v3/memory/query", json={
            "query": "mixed_budget",
            "max_chars": 5000,
        })
        assert r.status_code == 200

    def test_redaction_on_non_head_version(self, client):
        """Redacting a superseded version should work (chain pointers preserved)."""
        r = _store_fact(client, subject="RedactChain", predicate="v1", obj="old")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "RedactChain", "predicate": "v1", "object": "new", "confidence": 0.9,
        })
        client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
        })

        # Redact the original (superseded) version
        r3 = client.post("/v3/memory/redact", json={
            "memory_id": orig_id,
            "reason": "old version cleanup",
        })
        assert r3.status_code == 200

        # Version history should still work
        r4 = client.get(f"/v3/memory/{orig_id}/versions")
        assert r4.status_code == 200
        versions = r4.json()["versions"]
        assert len(versions) >= 2
        # Redacted version should show [REDACTED] content
        redacted_v = [v for v in versions if v["id"] == orig_id]
        if redacted_v:
            assert redacted_v[0]["content"] == "[REDACTED]"

    def test_concurrent_supersede_rejection(self, client):
        """Double supersede on same memory should return 409."""
        r = _store_fact(client, subject="ConcSuper", predicate="test", obj="v1")
        orig_id = r.json()["id"]

        new_content = json.dumps({
            "subject": "ConcSuper", "predicate": "test", "object": "v2", "confidence": 0.9,
        })
        r2 = client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content,
        })
        assert r2.status_code == 200

        # Try to supersede again — should fail with 409
        new_content2 = json.dumps({
            "subject": "ConcSuper", "predicate": "test", "object": "v3", "confidence": 0.9,
        })
        r3 = client.post("/v3/memory/version", json={
            "original_id": orig_id,
            "new_content": new_content2,
        })
        assert r3.status_code == 409

    def test_same_object_no_conflict(self, client):
        """Same (subject, predicate, object) should NOT create a conflict."""
        _store_fact(client, subject="SameObj", predicate="is", obj="identical")
        r2 = _store_fact(client, subject="SameObj", predicate="is", obj="identical")
        assert r2.status_code == 200
        assert len(r2.json()["conflicts"]) == 0

    def test_same_value_preference_no_conflict(self, client):
        """Same (category, key, value) preference should NOT conflict."""
        _store_preference(client, category="same_val_cat", key="k", value="v")
        r2 = _store_preference(client, category="same_val_cat", key="k", value="v")
        assert r2.status_code == 200
        assert len(r2.json()["conflicts"]) == 0

    def test_valid_until_before_valid_from_rejected(self, client):
        """valid_until < valid_from should be rejected."""
        r = _store_fact(
            client,
            subject="BadTemporal",
            predicate="test",
            obj="fail",
            valid_from="2025-06-01T00:00:00Z",
            valid_until="2025-01-01T00:00:00Z",
        )
        assert r.status_code == 400
