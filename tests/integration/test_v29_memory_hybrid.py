"""
v2.9 Memory Engine — Hybrid Search, Provenance, Token Budget Tests

Tests the wired BM25 + LIKE hybrid search pipeline, provenance tracking,
and retrieval token budget enforcement.
"""
import sys
import os
import json
import tempfile
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── Path setup ─────────────────────────────────────────────────────────
sys.path.insert(0, r"S:\services\memory-engine")


# ── Helpers ────────────────────────────────────────────────────────────

def make_test_db(tmp_path):
    """Create a real MemoryDatabase in a temp directory."""
    db_path = str(tmp_path / "test_memory.db")
    schema_path = Path(r"S:\services\memory-engine\schema.sql")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    conn.close()

    from db import MemoryDatabase
    db = MemoryDatabase(db_path=db_path)
    return db


# ═══════════════════════════════════════════════════════════════════════
# 1. BM25 Index Core Tests
# ═══════════════════════════════════════════════════════════════════════

class TestBM25Core:
    """Test the BM25 ranking algorithm directly."""

    def test_index_and_search(self):
        """BM25 indexes documents and returns ranked results."""
        from core.bm25 import BM25
        bm25 = BM25()

        bm25.index_document("doc1", "the quick brown fox jumps over the lazy dog")
        bm25.index_document("doc2", "a fast brown cat runs past the sleeping dog")
        bm25.index_document("doc3", "python programming language is widely used")

        results = bm25.search("brown fox", limit=10)
        assert len(results) > 0
        # doc1 should rank higher (has both "brown" and "fox")
        doc_ids = [r[0] for r in results]
        assert "doc1" in doc_ids
        assert doc_ids.index("doc1") < doc_ids.index("doc2") if "doc2" in doc_ids else True

    def test_empty_index_returns_empty(self):
        """BM25 search on empty index returns empty list."""
        from core.bm25 import BM25
        bm25 = BM25()
        results = bm25.search("anything", limit=10)
        assert results == []

    def test_stats(self):
        """BM25 stats track document count and tokens."""
        from core.bm25 import BM25
        bm25 = BM25()
        bm25.index_document("d1", "hello world")
        bm25.index_document("d2", "hello again")
        s = bm25.stats()
        assert s["num_documents"] == 2
        assert s["unique_tokens"] > 0


# ═══════════════════════════════════════════════════════════════════════
# 2. Hybrid Search Layer Tests
# ═══════════════════════════════════════════════════════════════════════

class TestHybridSearch:
    """Test the HybridSearchLayer wiring."""

    def test_initialize_preloads_bm25(self, tmp_path):
        """Hybrid search preloads existing ledger into BM25."""
        db = make_test_db(tmp_path)
        # Pre-populate ledger
        db.store("fact", "The capital of France is Paris")
        db.store("fact", "Python was created by Guido van Rossum")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        assert hybrid._initialized is True
        assert hybrid._indexed_count == 2

    def test_search_bm25_ranked(self, tmp_path):
        """Hybrid search returns BM25-ranked results."""
        db = make_test_db(tmp_path)
        db.store("fact", "Machine learning is a subset of artificial intelligence")
        db.store("fact", "Deep learning uses neural networks for AI")
        db.store("preference", "I prefer coffee over tea")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        results = hybrid.search("learning neural networks", limit=5)
        assert len(results) > 0
        # Results with BM25 scores should come first
        bm25_results = [r for r in results if r["source"] == "bm25"]
        assert len(bm25_results) > 0

    def test_search_like_fallback(self, tmp_path):
        """Hybrid search includes LIKE fallback results."""
        db = make_test_db(tmp_path)
        db.store("fact", "The sky is blue")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        # Search for exact substring that LIKE would catch
        results = hybrid.search("sky is blue", limit=5)
        assert len(results) > 0
        # Should find it via either BM25 or LIKE fallback
        content_list = [r["content"] for r in results]
        assert any("sky is blue" in c for c in content_list)

    def test_on_store_indexes_new_content(self, tmp_path):
        """New content stored via on_store() is searchable."""
        db = make_test_db(tmp_path)

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        # Store via db then index
        mid = db.store("fact", "Quantum computing uses qubits instead of bits")
        hybrid.on_store(mid, "Quantum computing uses qubits instead of bits")

        results = hybrid.search("quantum qubits", limit=5)
        assert len(results) > 0
        assert any("qubits" in r["content"] for r in results)

    def test_search_deduplicates(self, tmp_path):
        """Hybrid search doesn't return duplicate entries from BM25+LIKE."""
        db = make_test_db(tmp_path)
        mid = db.store("fact", "Python is a programming language")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        results = hybrid.search("Python programming", limit=10)
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids)), "Duplicate IDs in results"

    def test_search_respects_limit(self, tmp_path):
        """Hybrid search respects the limit parameter."""
        db = make_test_db(tmp_path)
        for i in range(20):
            db.store("fact", f"Test document number {i} about testing")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        results = hybrid.search("test document", limit=5)
        assert len(results) <= 5

    def test_get_stats_reflects_state(self, tmp_path):
        """get_stats() reflects initialization and index count."""
        db = make_test_db(tmp_path)
        db.store("fact", "hello world")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)

        # Before init
        stats = hybrid.get_stats()
        assert stats["initialized"] is False

        hybrid.initialize()
        stats = hybrid.get_stats()
        assert stats["initialized"] is True
        assert stats["bm25_indexed"] == 1

    def test_metadata_parsed_in_results(self, tmp_path):
        """Hybrid search results have parsed metadata dicts."""
        db = make_test_db(tmp_path)
        db.store("fact", "Test with metadata", metadata={"key": "value"})

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        results = hybrid.search("Test metadata", limit=5)
        assert len(results) > 0
        # Metadata should be a dict, not a JSON string
        for r in results:
            assert isinstance(r["metadata"], dict)


# ═══════════════════════════════════════════════════════════════════════
# 3. Provenance Tracker Tests
# ═══════════════════════════════════════════════════════════════════════

class TestProvenance:
    """Test provenance tracking via audit_log."""

    def test_track_and_retrieve(self, tmp_path):
        """Track provenance and retrieve it."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker

        tracker = ProvenanceTracker(db)
        tracker.track("mem_abc123", source_type="direct", source_id=None)

        record = tracker.get_provenance("mem_abc123")
        assert record["memory_id"] == "mem_abc123"
        assert record["source_type"] == "direct"

    def test_retrieve_from_db_fallback(self, tmp_path):
        """Provenance retrieval falls back to DB when not in memory."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker

        # Track with one instance
        tracker1 = ProvenanceTracker(db)
        tracker1.track("mem_xyz789", source_type="summary", source_id="mem_parent1")

        # Retrieve with a fresh instance (empty in-memory cache)
        tracker2 = ProvenanceTracker(db)
        record = tracker2.get_provenance("mem_xyz789")
        assert record["memory_id"] == "mem_xyz789"
        assert record["source_type"] == "summary"
        assert record["source_id"] == "mem_parent1"

    def test_provenance_chain(self, tmp_path):
        """Provenance chain follows source_id links."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker

        tracker = ProvenanceTracker(db)
        tracker.track("mem_child", source_type="chunk", source_id="mem_parent")
        tracker.track("mem_parent", source_type="direct", source_id=None)

        chain = tracker.get_chain("mem_child", max_depth=10)
        assert len(chain) == 2
        assert chain[0]["memory_id"] == "mem_child"
        assert chain[1]["memory_id"] == "mem_parent"

    def test_missing_provenance_returns_empty(self, tmp_path):
        """Missing provenance returns empty dict."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker

        tracker = ProvenanceTracker(db)
        record = tracker.get_provenance("nonexistent_id")
        assert record == {}

    def test_provenance_stats(self, tmp_path):
        """Stats reflect tracked records."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker

        tracker = ProvenanceTracker(db)
        tracker.track("mem_1", source_type="direct")
        tracker.track("mem_2", source_type="summary")

        stats = tracker.get_stats()
        assert stats["cached_records"] == 2
        assert "direct" in stats["source_types"]
        assert "summary" in stats["source_types"]


# ═══════════════════════════════════════════════════════════════════════
# 4. Token Budget Enforcement Tests
# ═══════════════════════════════════════════════════════════════════════

class TestTokenBudget:
    """Test retrieval token budget enforcement in /v1/search."""

    def test_budget_trims_results(self, tmp_path):
        """Token budget limits total content returned."""
        db = make_test_db(tmp_path)
        # Store several long documents
        for i in range(10):
            db.store("fact", f"Document {i}: " + "a" * 500)

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        # Search with no budget
        all_results = hybrid.search("Document", limit=10)
        assert len(all_results) > 2

        # Simulate budget enforcement (as done in /v1/search endpoint)
        max_tokens = 200  # ~800 chars, should fit about 1.5 docs
        budget = max_tokens * 4
        trimmed = []
        used = 0
        for r in all_results:
            content_len = len(r.get("content", ""))
            if used + content_len > budget and trimmed:
                break
            trimmed.append(r)
            used += content_len

        assert len(trimmed) < len(all_results)
        assert sum(len(r["content"]) for r in trimmed) <= budget + 600  # allow first doc overshoot

    def test_no_budget_returns_all(self, tmp_path):
        """No token budget returns all results up to limit."""
        db = make_test_db(tmp_path)
        for i in range(5):
            db.store("fact", f"Short doc {i}")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        results = hybrid.search("Short doc", limit=10)
        assert len(results) == 5


# ═══════════════════════════════════════════════════════════════════════
# 5. FastAPI Endpoint Wiring Tests (via TestClient)
# ═══════════════════════════════════════════════════════════════════════

class TestEndpointWiring:
    """Test that endpoints are properly wired in main.py."""

    @pytest.fixture(autouse=True)
    def setup_app(self, tmp_path):
        """Set up test app with temp database."""
        # Patch db before importing main
        db_path = str(tmp_path / "test_api.db")
        schema_path = Path(r"S:\services\memory-engine\schema.sql")
        conn = sqlite3.connect(db_path)
        if schema_path.exists():
            conn.executescript(schema_path.read_text())
        conn.close()

        from db import MemoryDatabase
        test_db = MemoryDatabase(db_path=db_path)

        import main as mem_main
        mem_main.db = test_db
        mem_main._hybrid = mem_main.HybridSearchLayer(test_db)
        mem_main._hybrid.initialize()
        mem_main._provenance = mem_main.ProvenanceTracker(test_db)

        from fastapi.testclient import TestClient
        self.client = TestClient(mem_main.app)
        self.db = test_db

    def test_store_indexes_in_hybrid(self):
        """POST /store indexes content in hybrid search."""
        resp = self.client.post("/store", json={
            "type": "fact",
            "content": "Gravity pulls objects toward each other",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stored"

        # Search via hybrid endpoint
        resp2 = self.client.post("/v1/search", json={
            "query": "gravity objects",
        })
        assert resp2.status_code == 200
        results = resp2.json()["results"]
        assert len(results) > 0
        assert any("Gravity" in r["content"] for r in results)

    def test_v1_search_returns_search_mode(self):
        """POST /v1/search returns search_mode=hybrid."""
        self.client.post("/store", json={
            "type": "fact", "content": "Water boils at 100 degrees Celsius"
        })
        resp = self.client.post("/v1/search", json={"query": "water boils"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["search_mode"] == "hybrid"

    def test_v1_search_with_token_budget(self):
        """POST /v1/search with max_tokens trims results."""
        for i in range(10):
            self.client.post("/store", json={
                "type": "fact",
                "content": f"Long document {i}: " + "x" * 400,
            })

        # With budget
        resp = self.client.post("/v1/search", json={
            "query": "Long document",
            "limit": 10,
            "max_tokens": 200,
        })
        assert resp.status_code == 200
        budget_results = resp.json()["results"]

        # Without budget
        resp2 = self.client.post("/v1/search", json={
            "query": "Long document",
            "limit": 10,
        })
        no_budget_results = resp2.json()["results"]

        assert len(budget_results) < len(no_budget_results)

    def test_provenance_endpoint(self):
        """GET /v1/provenance/{id} returns provenance data."""
        resp = self.client.post("/store", json={
            "type": "fact",
            "content": "Test provenance tracking",
            "metadata": {"source_type": "test_input"},
        })
        memory_id = resp.json()["id"]

        prov_resp = self.client.get(f"/v1/provenance/{memory_id}")
        assert prov_resp.status_code == 200
        data = prov_resp.json()
        assert data["provenance"]["memory_id"] == memory_id
        assert data["provenance"]["source_type"] == "test_input"

    def test_provenance_chain_endpoint(self):
        """GET /v1/provenance/{id}/chain returns chain."""
        resp = self.client.post("/store", json={
            "type": "fact",
            "content": "Chain test",
        })
        memory_id = resp.json()["id"]

        chain_resp = self.client.get(f"/v1/provenance/{memory_id}/chain")
        assert chain_resp.status_code == 200
        data = chain_resp.json()
        assert data["memory_id"] == memory_id
        assert isinstance(data["chain"], list)

    def test_healthz_includes_hybrid_stats(self):
        """GET /healthz includes hybrid_search stats."""
        resp = self.client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert "hybrid_search" in data
        assert data["hybrid_search"]["initialized"] is True

    def test_old_search_still_works(self):
        """POST /search (legacy) still works for backward compat."""
        self.client.post("/store", json={
            "type": "fact", "content": "Legacy search still works fine"
        })
        resp = self.client.post("/search", json={"query": "Legacy search"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0


# ═══════════════════════════════════════════════════════════════════════
# 6. No-Stubs Verification
# ═══════════════════════════════════════════════════════════════════════

class TestNoStubs:
    """Verify that previously stubbed code is now implemented."""

    def test_provenance_track_writes_to_db(self, tmp_path):
        """provenance.track() actually writes to audit_log, not a TODO stub."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker
        tracker = ProvenanceTracker(db)

        tracker.track("mem_test", source_type="direct")

        # Verify directly in DB
        with db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM audit_log WHERE operation = 'PROVENANCE' AND ledger_id = ?",
                ("mem_test",),
            ).fetchone()
        assert row is not None

    def test_provenance_get_reads_from_db(self, tmp_path):
        """provenance.get_provenance() actually reads from DB, not a stub."""
        db = make_test_db(tmp_path)
        from core.provenance import ProvenanceTracker

        # Write directly to DB
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        record = json.dumps({
            "memory_id": "mem_direct_write",
            "source_type": "test",
            "source_id": None,
            "metadata": {},
            "tracked_at": now,
        })
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO audit_log (id, operation, ledger_id, details, performed_at) VALUES (?, ?, ?, ?, ?)",
                (f"prov_{uuid.uuid4().hex[:12]}", "PROVENANCE", "mem_direct_write", record, now),
            )
            conn.commit()

        tracker = ProvenanceTracker(db)
        result = tracker.get_provenance("mem_direct_write")
        assert result["memory_id"] == "mem_direct_write"
        assert result["source_type"] == "test"

    def test_hybrid_search_not_like_only(self, tmp_path):
        """Hybrid search uses BM25 ranking, not just LIKE substring."""
        db = make_test_db(tmp_path)
        # Store documents with different relevance
        db.store("fact", "Machine learning algorithms process large datasets efficiently")
        db.store("fact", "The weather today is sunny and warm")
        db.store("fact", "Deep learning neural networks achieve state of the art results in machine vision")

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        results = hybrid.search("machine learning neural", limit=5)
        # BM25 should rank the ML documents higher
        bm25_hits = [r for r in results if r["source"] == "bm25"]
        assert len(bm25_hits) > 0, "Expected BM25-ranked results, got only LIKE fallback"
        # Top result should be about ML, not weather
        assert "learning" in results[0]["content"].lower() or "machine" in results[0]["content"].lower()
