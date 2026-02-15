"""Perception dedupe correctness tests (G20).

Tests:
    1. Exact duplicate drop behavior
    2. Near-duplicate coalesce behavior
    3. Unique event pass-through
    4. Mixed stream deterministic replay hash
    5. Dedupe window boundary (eviction) behavior
    6. Schema-version compatibility path
    7. Provenance chain completeness for every decision
"""
import pytest

from services.perception.event_normalizer import EventNormalizer, PerceptionEnvelope
from services.perception.dedupe_engine import (
    DedupeEngine, DECISION_DROP, DECISION_COALESCE, DECISION_ACCEPT,
)
from services.perception.provenance_hooks import ProvenanceChain
from services.perception.policy import PerceptionPipeline


# ── Helpers ──────────────────────────────────────────────────────────────

SID = "dedupe-session"
CID = "corr-dedupe"
normalizer = EventNormalizer()


def _raw(event_id, source="vision", event_type="entity_detection",
         object_id="person", summary="", confidence=0.9,
         bbox=None, schema_version="1.0.0"):
    raw = {
        "event_id": event_id,
        "session_id": SID,
        "source": source,
        "event_type": event_type,
        "object_id": object_id,
        "summary": summary or object_id,
        "confidence": confidence,
        "correlation_id": CID,
        "timestamp": 1000.0,
        "schema_version": schema_version,
    }
    if bbox:
        raw["bounding_box"] = bbox
    return raw


# ── Tests ────────────────────────────────────────────────────────────────

class TestDedupeCorrectness:

    def test_exact_duplicate_dropped(self):
        """Exact same event submitted twice: second is DROP_DUPLICATE."""
        engine = DedupeEngine(window_size=50)
        env1 = normalizer.normalize(_raw("evt-1"))
        env2 = normalizer.normalize(_raw("evt-2"))  # same fields = same dedupe_key

        d1 = engine.evaluate(env1)
        d2 = engine.evaluate(env2)

        assert d1.decision == DECISION_ACCEPT
        assert d2.decision == DECISION_DROP
        assert d2.parent_event_id == "evt-1"
        assert d2.reason_code == "exact_dedupe_key_match"
        assert engine.stats["total_dropped"] == 1

    def test_near_duplicate_coalesced(self):
        """Events with same object_id but slightly different confidence coalesce."""
        engine = DedupeEngine(window_size=50)
        env1 = normalizer.normalize(_raw("evt-1", confidence=0.85))
        env2 = normalizer.normalize(_raw("evt-2", confidence=0.90,
                                         summary="person detected"))

        d1 = engine.evaluate(env1)
        d2 = engine.evaluate(env2)

        assert d1.decision == DECISION_ACCEPT
        assert d2.decision == DECISION_COALESCE
        assert d2.parent_event_id == "evt-1"
        assert d2.reason_code == "near_duplicate_coalesce"
        assert engine.stats["total_coalesced"] == 1

    def test_unique_events_accepted(self):
        """Events with different object_ids are all accepted."""
        engine = DedupeEngine(window_size=50)

        labels = ["person", "dog", "laptop", "cup"]
        decisions = []
        for i, label in enumerate(labels):
            env = normalizer.normalize(_raw(f"evt-{i}", object_id=label, summary=label))
            decisions.append(engine.evaluate(env))

        assert all(d.decision == DECISION_ACCEPT for d in decisions)
        assert engine.stats["total_accepted"] == 4

    def test_mixed_stream_deterministic_replay_hash(self):
        """Same event stream replayed twice produces identical decision hash."""
        events = [
            _raw("e1", object_id="person", summary="person"),
            _raw("e2", object_id="dog", summary="dog"),
            _raw("e3", object_id="person", summary="person"),  # exact dup of e1
            _raw("e4", object_id="dog", summary="dog modified", confidence=0.88),  # near-dup
            _raw("e5", object_id="laptop", summary="laptop"),
        ]

        hashes = []
        for _ in range(2):
            engine = DedupeEngine(window_size=50)
            for raw in events:
                env = normalizer.normalize(raw)
                engine.evaluate(env)
            hashes.append(engine.replay_decisions_hash())

        assert hashes[0] == hashes[1], "Replay hash must be deterministic"

    def test_window_boundary_eviction(self):
        """When window is full, oldest entry is evicted and new entry accepted."""
        window_size = 5
        engine = DedupeEngine(window_size=window_size)

        # Fill window with 5 unique events
        for i in range(5):
            env = normalizer.normalize(_raw(f"fill-{i}", object_id=f"obj-{i}", summary=f"obj-{i}"))
            d = engine.evaluate(env)
            assert d.decision == DECISION_ACCEPT

        assert engine.window_count == 5

        # Add 6th -- should evict oldest (fill-0)
        env6 = normalizer.normalize(_raw("fill-5", object_id="obj-5", summary="obj-5"))
        d6 = engine.evaluate(env6)
        assert d6.decision == DECISION_ACCEPT
        assert engine.window_count == 5  # still capped

        # Now re-submit fill-0 -- should be accepted (was evicted)
        env0_again = normalizer.normalize(_raw("fill-0-again", object_id="obj-0", summary="obj-0"))
        d0 = engine.evaluate(env0_again)
        assert d0.decision == DECISION_ACCEPT  # not a dup anymore

    def test_schema_version_compatibility(self):
        """Different schema versions produce different dedupe keys."""
        engine = DedupeEngine(window_size=50)
        env1 = normalizer.normalize(_raw("sv1", schema_version="1.0.0"))
        env2 = normalizer.normalize(_raw("sv2", schema_version="2.0.0"))

        d1 = engine.evaluate(env1)
        d2 = engine.evaluate(env2)

        # Different schema version = different dedupe key = both accepted
        assert d1.decision == DECISION_ACCEPT
        assert d2.decision == DECISION_ACCEPT

    def test_provenance_chain_completeness(self):
        """Every dedupe decision has a corresponding provenance record."""
        pipeline = PerceptionPipeline(dedupe_window=50)
        events = [
            _raw("p1", object_id="person", summary="person"),
            _raw("p2", object_id="dog", summary="dog"),
            _raw("p3", object_id="person", summary="person"),  # dup
        ]

        for raw in events:
            pipeline.process_raw(raw)

        chain = pipeline.provenance
        dedupe_records = [r for r in chain.records if r.record_type == "dedupe"]
        assert len(dedupe_records) == 3  # one per input event

        # First two are ACCEPT, third is DROP
        assert dedupe_records[0].decision == DECISION_ACCEPT
        assert dedupe_records[1].decision == DECISION_ACCEPT
        assert dedupe_records[2].decision == DECISION_DROP
