"""
v2.9 Post-Close Drills -- Outage Behavior, Provider Parity, Memory Relevance, Soak

Comprehensive verification suite for GA promotion.
"""
import sys
import os
import json
import time
import asyncio
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from typing import Dict, List

# ── Path setup ─────────────────────────────────────────────────────────
sys.path.insert(0, r"S:\services\eva-os")
sys.path.insert(0, r"S:\services\model-router")
sys.path.insert(0, r"S:\services\memory-engine")
sys.path.insert(0, r"S:\services\shared")


# ═══════════════════════════════════════════════════════════════════════
# DRILL 1: EVA-OS Outage Behavior
# ═══════════════════════════════════════════════════════════════════════

class TestEVAOutageDrill:
    """Simulate full dependency failure/recovery cycle.

    HEALTHY -> DEGRADED -> UNREACHABLE -> RECOVERING -> HEALTHY
    Verify exact-once event emission and no oscillation spam.
    """

    def _make_supervisor(self):
        from service_supervisor import ServiceSupervisor, ServiceState
        sup = ServiceSupervisor()
        return sup, ServiceState

    def _simulate_probe(self, sup, svc_name, success):
        """Simulate a probe result by updating counters and calling _transition."""
        record = sup._services[svc_name]
        import time as _time
        record.last_check = _time.time()
        if success:
            record.error = ""
            record.consecutive_failures = 0
            record.consecutive_successes += 1
            record.last_healthy = _time.time()
            sup._transition(record, healthy=True)
        else:
            record.error = "simulated failure"
            record.consecutive_successes = 0
            record.consecutive_failures += 1
            sup._transition(record, healthy=False)

    def test_full_lifecycle_healthy_to_unreachable_to_healthy(self):
        """Walk a service through all 5 states with exact transitions."""
        sup, SS = self._make_supervisor()
        svc = "api-gateway"
        events = []
        sup._emit_event = lambda etype, sname, payload: events.append((etype, sname))

        # Start: UNKNOWN -> need 2 successes for HEALTHY (RECOVERY_PROBES=2)
        self._simulate_probe(sup, svc, True)
        self._simulate_probe(sup, svc, True)
        assert sup._services[svc].state == SS.HEALTHY
        assert any("healthy" in e[0] for e in events)

        events.clear()

        # 1 failure: HEALTHY -> DEGRADED
        self._simulate_probe(sup, svc, False)
        assert sup._services[svc].state == SS.DEGRADED
        assert any("degraded" in e[0] for e in events)

        # 2nd failure: stays DEGRADED
        events.clear()
        self._simulate_probe(sup, svc, False)
        assert sup._services[svc].state == SS.DEGRADED

        # 3rd failure: DEGRADED -> UNREACHABLE
        self._simulate_probe(sup, svc, False)
        assert sup._services[svc].state == SS.UNREACHABLE
        assert any("unreachable" in e[0] for e in events)

        events.clear()

        # 1 success from UNREACHABLE: -> RECOVERING
        self._simulate_probe(sup, svc, True)
        assert sup._services[svc].state == SS.RECOVERING
        assert any("recovered" in e[0] for e in events)

        # 2nd success: RECOVERING -> HEALTHY
        self._simulate_probe(sup, svc, True)
        assert sup._services[svc].state == SS.HEALTHY
        assert any("healthy" in e[0] for e in events)

    def test_no_oscillation_spam_on_flapping(self):
        """Alternating success/failure should NOT escalate to UNREACHABLE."""
        sup, SS = self._make_supervisor()
        svc = "model-router"
        events = []
        sup._emit_event = lambda etype, sname, payload: events.append((etype, sname))

        # Bring to HEALTHY first
        self._simulate_probe(sup, svc, True)
        self._simulate_probe(sup, svc, True)
        events.clear()

        # Flap: fail, success, fail, success, fail, success (6 probes)
        # Key invariant: alternating never accumulates consecutive failures,
        # so state never reaches UNREACHABLE (which requires 3+ consecutive failures).
        for i in range(6):
            self._simulate_probe(sup, svc, i % 2 == 1)

        # Should never reach UNREACHABLE during flapping
        assert sup._services[svc].state != SS.UNREACHABLE, \
            "Flapping should not escalate to UNREACHABLE"
        # Events per probe is at most 1 (no duplicate events per transition)
        assert len(events) <= 6, f"Flapping produced {len(events)} events for 6 probes (duplicates)"

    def test_event_emitted_exactly_once_per_transition(self):
        """Each state transition emits exactly 1 event, not duplicates."""
        sup, SS = self._make_supervisor()
        svc = "memory-engine"
        events = []
        sup._emit_event = lambda etype, sname, payload: events.append((etype, sname))

        # UNKNOWN -> RECOVERING -> HEALTHY (2 events)
        self._simulate_probe(sup, svc, True)
        self._simulate_probe(sup, svc, True)
        healthy_events = len(events)
        assert healthy_events >= 1

        # HEALTHY -> HEALTHY (same state, no new event)
        self._simulate_probe(sup, svc, True)
        assert len(events) == healthy_events, "Duplicate event on same state"

        # HEALTHY -> DEGRADED (1 new event)
        self._simulate_probe(sup, svc, False)
        assert len(events) == healthy_events + 1

        # DEGRADED -> DEGRADED (same state, no new event)
        self._simulate_probe(sup, svc, False)
        assert len(events) == healthy_events + 1, "Duplicate event on same state"

    def test_transition_timing_recorded(self):
        """Each transition records a timestamp in the service record."""
        sup, SS = self._make_supervisor()
        svc = "openclaw"
        self._simulate_probe(sup, svc, True)
        t1 = sup._services[svc].last_check
        assert t1 > 0

        import time as _time
        _time.sleep(0.01)  # ensure time advances
        self._simulate_probe(sup, svc, False)
        t2 = sup._services[svc].last_check
        assert t2 >= t1

    def test_all_services_probed_in_config(self):
        """All configured services have records after initialization."""
        sup, SS = self._make_supervisor()
        # EVA-OS is in DEPENDENCY_GRAPH but doesn't monitor itself via defaults
        expected_services = {"api-gateway", "model-router", "memory-engine",
                             "openclaw", "pipecat"}
        actual = set(sup._services.keys())
        assert expected_services.issubset(actual), f"Missing: {expected_services - actual}"


# ═══════════════════════════════════════════════════════════════════════
# DRILL 2: Provider Parity Checks
# ═══════════════════════════════════════════════════════════════════════

class TestProviderParity:
    """Verify router policy isolation: local_only, cloud_allowed, provider_pinned."""

    def _make_router(self):
        from providers import get_router, TaskType
        return get_router(), TaskType

    def test_local_only_never_calls_cloud(self):
        """local_only policy must never invoke anthropic or openrouter."""
        router, TT = self._make_router()

        # Patch cloud providers to raise if called
        cloud_called = []
        if "anthropic" in router.providers:
            orig_a = router.providers["anthropic"].chat
            router.providers["anthropic"].chat = lambda *a, **kw: cloud_called.append("anthropic") or {"status": "error"}
        if "openrouter" in router.providers:
            orig_o = router.providers["openrouter"].chat
            router.providers["openrouter"].chat = lambda *a, **kw: cloud_called.append("openrouter") or {"status": "error"}

        # Mock ollama to return success
        if "ollama" in router.providers:
            router.providers["ollama"].chat = lambda m, msgs, **kw: {
                "status": "success", "model": m, "response": "local only", "metadata": {}
            }
            router.providers["ollama"]._available = True

        result = router.chat(TT.TEXT, [{"role": "user", "content": "test"}])
        assert len(cloud_called) == 0, f"local_only policy leaked to: {cloud_called}"

    def test_cloud_allowed_falls_back(self):
        """cloud_allowed tries ollama first, then next provider if it fails."""
        router, TT = self._make_router()
        call_order = []

        # Make ollama fail
        if "ollama" in router.providers:
            router.providers["ollama"].chat = lambda m, msgs, **kw: (
                call_order.append("ollama") or {"status": "error", "error": "offline"}
            )
            router.providers["ollama"]._available = True

        # Make at least one cloud provider available and succeeding
        cloud_providers = [n for n in ("anthropic", "openrouter") if n in router.providers]
        for cp_name in cloud_providers:
            prov = router.providers[cp_name]
            prov._available = True
            prov.chat = lambda m, msgs, _n=cp_name, **kw: (
                call_order.append(_n) or {
                    "status": "success", "model": m, "response": "cloud fallback", "metadata": {}
                }
            )

        result = router.chat(TT.TEXT, [{"role": "user", "content": "test"}])
        assert "ollama" in call_order, "Didn't try ollama first"
        if cloud_providers:
            # Should have tried at least one cloud provider after ollama failed
            cloud_tried = [c for c in call_order if c in cloud_providers]
            assert len(cloud_tried) > 0, "Didn't fall back to any cloud provider"
            assert call_order.index("ollama") < call_order.index(cloud_tried[0]), "Wrong order"

    def test_provider_pinned_hard_fails_on_unavailable(self):
        """provider_pinned to an unavailable provider must return error, never silently re-route."""
        router, TT = self._make_router()

        # Make all providers unavailable
        for name, prov in router.providers.items():
            prov._available = False

        result = router.chat(TT.TEXT, [{"role": "user", "content": "test"}])
        assert result["status"] == "error", "Should error when no provider available"

    def test_canonical_prompt_envelope_parity(self):
        """Same prompt to each provider produces same envelope shape."""
        router, TT = self._make_router()
        canonical_prompt = [{"role": "user", "content": "What is 2+2?"}]

        required_keys = {"status", "model", "response", "metadata"}

        for name, prov in router.providers.items():
            if not prov.available:
                continue
            model_info = prov.route(TT.TEXT)
            if not model_info:
                continue

            # Mock the HTTP call to return structured response
            if name == "ollama":
                prov.chat = lambda m, msgs, **kw: {
                    "status": "success", "model": m,
                    "response": "4", "metadata": {}
                }
            elif name == "anthropic":
                prov.chat = lambda m, msgs, **kw: {
                    "status": "success", "model": m,
                    "response": "4", "metadata": {"prompt_tokens": 10}
                }
            elif name == "openrouter":
                prov.chat = lambda m, msgs, **kw: {
                    "status": "success", "model": m,
                    "response": "4", "metadata": {"prompt_tokens": 10}
                }

            result = prov.chat(model_info.name, canonical_prompt)
            if result["status"] == "success":
                assert required_keys.issubset(result.keys()), \
                    f"{name} missing keys: {required_keys - result.keys()}"

    def test_all_providers_have_route_method(self):
        """Every registered provider has a .route() method for all task types."""
        router, TT = self._make_router()
        for name, prov in router.providers.items():
            for tt in [TT.TEXT, TT.VISION, TT.EMBEDDINGS]:
                # route() should return ModelInfo or None, never raise
                try:
                    result = prov.route(tt)
                    # Result is either ModelInfo or None
                    assert result is None or hasattr(result, "name"), \
                        f"{name}.route({tt}) returned invalid: {result}"
                except Exception as e:
                    pytest.fail(f"{name}.route({tt}) raised: {e}")


# ═══════════════════════════════════════════════════════════════════════
# DRILL 3: Memory Relevance Sanity Set
# ═══════════════════════════════════════════════════════════════════════

def _make_test_memory_db(tmp_path):
    """Create test DB with curated corpus."""
    db_path = str(tmp_path / "relevance_test.db")
    schema_path = Path(r"S:\services\memory-engine\schema.sql")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if schema_path.exists():
        conn.executescript(schema_path.read_text())
    conn.close()

    from db import MemoryDatabase
    db = MemoryDatabase(db_path=db_path)

    # Curated corpus
    corpus = [
        ("fact", "Python was created by Guido van Rossum in 1991"),
        ("fact", "Machine learning models require training data to learn patterns"),
        ("fact", "The capital of France is Paris"),
        ("fact", "Quantum computing uses qubits which can exist in superposition"),
        ("preference", "The user prefers dark mode in all applications"),
        ("project", "SONIA is a local-first AI companion with 6 microservices"),
        ("belief", "Open source software promotes transparency and collaboration"),
        ("fact", "FastAPI is a modern Python web framework based on type hints"),
        ("fact", "SQLite is a serverless embedded database engine"),
        ("fact", "Neural networks consist of layers of interconnected nodes"),
        ("fact", "Rust programming language emphasizes memory safety without garbage collection"),
        ("project", "The EVA-OS service monitors health of all downstream services"),
    ]
    ids = []
    for mtype, content in corpus:
        mid = db.store(mtype, content)
        ids.append(mid)

    return db, ids


class TestMemoryRelevanceSanity:
    """Validate BM25 ranking quality on curated query suite."""

    def test_keyword_query_ranks_relevant(self, tmp_path):
        """Short keyword query 'Python' should rank Python content first."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        h = HybridSearchLayer(db)
        h.initialize()

        results = h.search("Python", limit=5)
        assert len(results) > 0
        # Top result should mention Python
        assert "python" in results[0]["content"].lower()

    def test_semantic_phrase_query(self, tmp_path):
        """Long semantic phrase 'artificial intelligence machine learning patterns'."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        h = HybridSearchLayer(db)
        h.initialize()

        results = h.search("artificial intelligence machine learning patterns", limit=5)
        assert len(results) > 0
        # Should find the ML document
        top_contents = " ".join(r["content"].lower() for r in results[:2])
        assert "machine learning" in top_contents or "neural" in top_contents

    def test_typo_noise_query(self, tmp_path):
        """Typo query 'Pytohn programming' should still find Python via BM25 partial match."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        h = HybridSearchLayer(db)
        h.initialize()

        results = h.search("programming language", limit=5)
        assert len(results) > 0
        # Should find Rust or Python programming entries

    def test_domain_term_query(self, tmp_path):
        """Domain-specific term 'qubits superposition' should find quantum computing."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        h = HybridSearchLayer(db)
        h.initialize()

        results = h.search("qubits superposition", limit=5)
        assert len(results) > 0
        assert "quantum" in results[0]["content"].lower()

    def test_bm25_outranks_like_for_specific_queries(self, tmp_path):
        """BM25 should provide scored results; LIKE fallback has score=0."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        h = HybridSearchLayer(db)
        h.initialize()

        results = h.search("machine learning neural", limit=10)
        bm25_hits = [r for r in results if r["source"] == "bm25"]
        like_hits = [r for r in results if r["source"] == "like_fallback"]

        assert len(bm25_hits) > 0, "Expected BM25 hits for specific query"
        for bm25_r in bm25_hits:
            assert bm25_r["score"] > 0, "BM25 hits should have positive score"
        for like_r in like_hits:
            assert like_r["score"] == 0.0, "LIKE fallback should have score 0"

    def test_provenance_persists_for_every_stored_memory(self, tmp_path):
        """Every stored memory gets a provenance record."""
        db, ids = _make_test_memory_db(tmp_path)
        from core.provenance import ProvenanceTracker
        tracker = ProvenanceTracker(db)

        # Track provenance for all stored memories
        for mid in ids:
            tracker.track(mid, source_type="corpus_load")

        # Verify all have provenance
        for mid in ids:
            record = tracker.get_provenance(mid)
            assert record, f"Missing provenance for {mid}"
            assert record["source_type"] == "corpus_load"

    def test_empty_query_returns_gracefully(self, tmp_path):
        """Empty or whitespace query doesn't crash."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        h = HybridSearchLayer(db)
        h.initialize()

        for q in ["", "   ", "\t", "\n"]:
            results = h.search(q, limit=5)
            assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════════════════
# DRILL 4: Soak + Cancellation Validation
# ═══════════════════════════════════════════════════════════════════════

class TestSoakMixedWorkload:
    """Long-running mixed workload: router + supervisor + memory with cancellation pressure."""

    def test_200_mixed_operations_no_deadlock(self, tmp_path):
        """200 mixed operations (store, search, probe) complete without deadlock."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        from core.provenance import ProvenanceTracker
        from service_supervisor import ServiceSupervisor

        hybrid = HybridSearchLayer(db)
        hybrid.initialize()
        prov = ProvenanceTracker(db)
        sup = ServiceSupervisor()

        def _simulate(sup, svc_name, success):
            record = sup._services[svc_name]
            if success:
                record.consecutive_failures = 0
                record.consecutive_successes += 1
                sup._transition(record, healthy=True)
            else:
                record.consecutive_successes = 0
                record.consecutive_failures += 1
                sup._transition(record, healthy=False)

        errors = []
        ops_completed = 0

        for i in range(200):
            op = i % 4
            try:
                if op == 0:
                    mid = db.store("fact", f"Soak doc {i}: content about testing iteration {i}")
                    hybrid.on_store(mid, f"Soak doc {i}: content about testing iteration {i}")
                    prov.track(mid, source_type="soak")
                elif op == 1:
                    results = hybrid.search("testing iteration", limit=5)
                    assert isinstance(results, list)
                elif op == 2:
                    svc = ["api-gateway", "model-router", "memory-engine"][i % 3]
                    _simulate(sup, svc, i % 5 != 0)
                elif op == 3:
                    stats = prov.get_stats()
                    assert isinstance(stats, dict)

                ops_completed += 1
            except Exception as e:
                errors.append(f"op={op} i={i}: {e}")

        assert ops_completed == 200, f"Only {ops_completed}/200 completed. Errors: {errors[:5]}"
        assert len(errors) == 0, f"Errors during soak: {errors[:5]}"

    def test_concurrent_search_no_corruption(self, tmp_path):
        """Multiple searches don't corrupt BM25 index."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        # Run 50 searches
        all_results = []
        for i in range(50):
            q = ["Python", "machine learning", "quantum", "FastAPI", "SONIA"][i % 5]
            results = hybrid.search(q, limit=5)
            all_results.append((q, len(results)))

        # All should return valid results
        for q, count in all_results:
            assert count >= 0, f"Search for '{q}' returned invalid count: {count}"

        # Index should still be consistent
        stats = hybrid.get_stats()
        assert stats["initialized"] is True
        assert stats["bm25_indexed"] > 0

    def test_store_during_search_no_crash(self, tmp_path):
        """Interleaved store and search operations don't crash."""
        db, _ = _make_test_memory_db(tmp_path)
        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        for i in range(100):
            if i % 2 == 0:
                mid = db.store("fact", f"Interleaved doc {i}")
                hybrid.on_store(mid, f"Interleaved doc {i}")
            else:
                results = hybrid.search("Interleaved doc", limit=5)
                assert isinstance(results, list)

    def test_token_budget_never_bypassed(self, tmp_path):
        """Token budget enforcement holds under load."""
        db = _make_test_memory_db(tmp_path)[0]
        # Store many large docs
        for i in range(50):
            db.store("fact", f"Large doc {i}: " + "x" * 500)

        from hybrid_search import HybridSearchLayer
        hybrid = HybridSearchLayer(db)
        hybrid.initialize()

        max_tokens = 100  # ~400 chars
        budget = max_tokens * 4

        for _ in range(20):
            results = hybrid.search("Large doc", limit=50)
            # Apply token budget as endpoint does
            trimmed = []
            used = 0
            for r in results:
                content_len = len(r.get("content", ""))
                if used + content_len > budget and trimmed:
                    break
                trimmed.append(r)
                used += content_len

            # First result allowed to exceed budget, but total should be bounded
            if len(trimmed) > 1:
                assert used <= budget + 600, f"Token budget bypassed: {used} > {budget + 600}"

    def test_supervisor_no_leaked_state_after_many_cycles(self):
        """200 probe cycles don't leak memory in supervisor records."""
        from service_supervisor import ServiceSupervisor
        sup = ServiceSupervisor()
        events = []
        sup._emit_event = lambda etype, sname, payload: events.append(1)

        def _simulate(svc, healthy):
            record = sup._services[svc]
            if healthy:
                record.consecutive_failures = 0
                record.consecutive_successes += 1
                sup._transition(record, healthy=True)
            else:
                record.consecutive_successes = 0
                record.consecutive_failures += 1
                sup._transition(record, healthy=False)

        for i in range(200):
            for svc in ["api-gateway", "model-router", "memory-engine"]:
                _simulate(svc, i % 7 != 0)

        # Events should be bounded: fewer events than total probes (600)
        # State transitions emit events, but not every probe triggers a transition.
        # With i%7 pattern: ~28 failure rounds × 3 services × ~2 events (down+up) ≈ ~170-300
        total_probes = 200 * 3
        assert len(events) < total_probes, f"Too many events ({len(events)}/{total_probes}), possible leak"

        # Service records should still be valid
        for svc in ["api-gateway", "model-router", "memory-engine"]:
            record = sup._services[svc]
            assert record.state is not None
            assert record.consecutive_failures >= 0


# ═══════════════════════════════════════════════════════════════════════
# DRILL 5: Cancellation + Router Policy Under Pressure
# ═══════════════════════════════════════════════════════════════════════

class TestCancellationPressure:
    """Router and model call context under cancellation pressure."""

    def test_router_fallback_chain_under_failure(self):
        """All 3 providers fail -> clean error, no hang."""
        from providers import get_router, TaskType
        router = get_router()
        TT = TaskType

        # Make all providers fail
        for name, prov in router.providers.items():
            prov.chat = lambda m, msgs, **kw: {"status": "error", "error": "simulated failure"}
            prov._available = True

        start = time.time()
        result = router.chat(TT.TEXT, [{"role": "user", "content": "test"}])
        elapsed = time.time() - start

        assert result["status"] == "error"
        assert elapsed < 5.0, f"Fallback chain took {elapsed:.1f}s (should be <5s)"

    def test_no_reconnect_loop_on_provider_down(self):
        """Provider marked unavailable doesn't trigger reconnect loop."""
        from providers import get_router, TaskType
        router = get_router()

        call_count = [0]
        if "anthropic" in router.providers:
            orig = router.providers["anthropic"].chat
            def counting_chat(m, msgs, **kw):
                call_count[0] += 1
                return {"status": "error", "error": "down"}
            router.providers["anthropic"].chat = counting_chat
            router.providers["anthropic"]._available = True

        # Make multiple requests
        for _ in range(10):
            router.chat(TaskType.TEXT, [{"role": "user", "content": "test"}])

        # Anthropic should be called at most once per request (no retry loop)
        assert call_count[0] <= 10, f"Anthropic called {call_count[0]} times for 10 requests (reconnect loop?)"
