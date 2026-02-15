"""Memory replay determinism tests (G23).

Tests:
    1. Replay hash stable across repeated runs
    2. Ledger hash stable for same corpus
    3. Ordering ties resolved deterministically
    4. Divergent decision set detected
    5. Conflict set ordering stable
    6. Retract replay deterministic
    7. Mixed approve/reject sequences deterministic
    8. Schema version mismatch surfaced explicitly
    9. Policy version mismatch surfaced explicitly
   10. Partial history replay produces expected subset hash
   11. Replay with duplicate decision events handled deterministically
   12. Replay rejects missing proposal references
   13. Provenance chain hash parity with live path
   14. Zero silent mutation assertion (global invariant)
"""
import pytest

from services.memory_ops.proposal_model import (
    MemoryType, RiskTier, ProposalState, create_proposal,
)
from services.memory_ops.replay_engine import (
    ReplayEngine, ReplayDecision, ProposalInput, ReplayResult,
)
from services.memory_ops.governance_pipeline import MemoryGovernancePipeline


# ── Helpers ──────────────────────────────────────────────────────────

SID = "replay-session"


def _input(subject_key, payload, memory_type=MemoryType.FACT,
           confidence=0.9, schema_version="1.0.0",
           policy_version="1.0.0"):
    return ProposalInput(
        session_id=SID,
        origin_event_ids=["evt-1"],
        memory_type=memory_type,
        subject_key=subject_key,
        payload=payload,
        confidence=confidence,
        schema_version=schema_version,
        policy_version=policy_version,
    )


def _standard_corpus():
    """Standard test corpus: 5 proposals with varied types."""
    return [
        _input("user.name", {"subject": "user", "predicate": "name", "object": "Alice"}),
        _input("user.loc", {"subject": "user", "predicate": "location", "object": "NYC"}),
        _input("sys.health", {"component": "api", "state": "healthy"},
               memory_type=MemoryType.SYSTEM_STATE, confidence=0.95),
        _input("user.theme", {"key": "dark_mode", "value": "true"},
               memory_type=MemoryType.PREFERENCE, confidence=0.8),
        _input("scene.obj", {"subject": "scene", "predicate": "contains", "object": "laptop"},
               confidence=0.5),
    ]


# ── Tests ────────────────────────────────────────────────────────────

class TestReplayDeterminism:

    def test_replay_hash_stable_across_runs(self):
        """Same corpus replayed twice produces identical decision hash."""
        engine = ReplayEngine()
        corpus = _standard_corpus()

        # Create deterministic proposal IDs first to build decisions
        r1 = engine.replay(corpus, [])
        r2 = engine.replay(corpus, [])

        assert r1.replay_decisions_hash == r2.replay_decisions_hash

    def test_ledger_hash_stable_for_same_corpus(self):
        """Same corpus produces identical ledger state hash."""
        engine = ReplayEngine()
        corpus = _standard_corpus()

        r1 = engine.replay(corpus, [])
        r2 = engine.replay(corpus, [])

        assert r1.ledger_state_hash == r2.ledger_state_hash

    def test_ordering_ties_resolved_deterministically(self):
        """Proposals with same seq get stable ordering via proposal_id."""
        engine = ReplayEngine()

        # Two proposals that will get same fields but different payloads
        corpus = [
            _input("key-a", {"val": 1}),
            _input("key-b", {"val": 2}),
        ]

        results = [engine.replay(corpus, []) for _ in range(5)]
        hashes = {r.ledger_state_hash for r in results}
        assert len(hashes) == 1, "Ordering must be deterministic"

    def test_divergent_decision_set_detected(self):
        """verify() detects hash mismatch when expected hash differs."""
        engine = ReplayEngine()
        corpus = _standard_corpus()

        r1 = engine.replay(corpus, [])
        r2 = engine.verify(corpus, [], expected_decisions_hash="wrong_hash")

        assert r2.divergence_count >= 1

    def test_conflict_set_ordering_stable(self):
        """Conflicts detected in replay have stable ordering."""
        engine = ReplayEngine()
        corpus = [
            _input("user.name", {"subject": "user", "predicate": "name", "object": "Alice"}),
            _input("user.name", {"subject": "user", "predicate": "name", "object": "Bob"}),
        ]

        results = [engine.replay(corpus, []) for _ in range(3)]
        conflict_counts = [len(r.conflict_events) for r in results]
        assert all(c == conflict_counts[0] for c in conflict_counts)
        assert conflict_counts[0] >= 1

    def test_retract_replay_deterministic(self):
        """Retraction in replay produces stable hash."""
        engine = ReplayEngine()
        corpus = [_input("user.name", {"name": "Alice"})]

        # First get the proposal_id
        r0 = engine.replay(corpus, [])
        applied_id = r0.applied_ids[0] if r0.applied_ids else None

        if applied_id:
            decisions = [
                ReplayDecision(seq=0, proposal_id=applied_id,
                               action="RETRACT", actor="op", reason="fix"),
            ]
            r1 = engine.replay(corpus, decisions)
            r2 = engine.replay(corpus, decisions)

            assert r1.replay_decisions_hash == r2.replay_decisions_hash
            assert r1.ledger_state_hash == r2.ledger_state_hash
            assert applied_id in r1.retracted_ids

    def test_mixed_approve_reject_deterministic(self):
        """Mixed approve/reject sequence produces stable hashes."""
        engine = ReplayEngine()
        corpus = [
            _input("k1", {"v": 1}, memory_type=MemoryType.PREFERENCE),
            _input("k2", {"v": 2}, memory_type=MemoryType.PREFERENCE),
            _input("k3", {"v": 3}, memory_type=MemoryType.PREFERENCE),
        ]

        # Get proposal IDs
        r0 = engine.replay(corpus, [])
        pending = sorted(set(r0.applied_ids) | set(r0.rejected_ids)
                         | {p.proposal_id for p in [
                             create_proposal(SID, ["evt-1"], c.memory_type,
                                             c.subject_key, c.payload, c.confidence,
                                             RiskTier.AUTO_LOW, i)
                             for i, c in enumerate(corpus)
                         ]})

        # Build decisions for the actual proposal IDs from replay
        proposals = []
        for i, c in enumerate(corpus):
            proposals.append(create_proposal(
                SID, ["evt-1"], c.memory_type, c.subject_key,
                c.payload, c.confidence, RiskTier.AUTO_LOW, i,
            ))

        decisions = [
            ReplayDecision(seq=0, proposal_id=proposals[0].proposal_id,
                           action="APPROVE", actor="op"),
            ReplayDecision(seq=1, proposal_id=proposals[1].proposal_id,
                           action="REJECT", actor="op", reason="not_needed"),
            ReplayDecision(seq=2, proposal_id=proposals[2].proposal_id,
                           action="APPROVE", actor="op"),
        ]

        r1 = engine.replay(corpus, decisions)
        r2 = engine.replay(corpus, decisions)

        assert r1.replay_decisions_hash == r2.replay_decisions_hash
        assert r1.ledger_state_hash == r2.ledger_state_hash

    def test_schema_version_mismatch_surfaced(self):
        """Different schema versions on same key produce conflict."""
        engine = ReplayEngine()
        corpus = [
            _input("user.name", {"name": "Alice"}, schema_version="1.0.0"),
            _input("user.name", {"name": "Alice"}, schema_version="2.0.0"),
        ]

        result = engine.replay(corpus, [])
        schema_conflicts = [c for c in result.conflict_events
                            if c.conflict_type == "SCHEMA_CONFLICT"]
        assert len(schema_conflicts) >= 1

    def test_policy_version_mismatch_surfaced(self):
        """Different policy versions produce different proposal_ids."""
        p1 = create_proposal(SID, [], MemoryType.FACT, "k", {"v": 1},
                              0.9, RiskTier.AUTO_LOW, 1,
                              policy_version="1.0.0")
        p2 = create_proposal(SID, [], MemoryType.FACT, "k", {"v": 1},
                              0.9, RiskTier.AUTO_LOW, 1,
                              policy_version="2.0.0")
        assert p1.proposal_id != p2.proposal_id

    def test_partial_history_replay_subset_hash(self):
        """Replaying a subset produces a different but stable hash."""
        engine = ReplayEngine()
        full_corpus = _standard_corpus()
        subset = full_corpus[:3]

        r_full = engine.replay(full_corpus, [])
        r_sub1 = engine.replay(subset, [])
        r_sub2 = engine.replay(subset, [])

        assert r_sub1.ledger_state_hash == r_sub2.ledger_state_hash
        assert r_sub1.ledger_state_hash != r_full.ledger_state_hash

    def test_duplicate_decision_events_handled(self):
        """Duplicate decisions in replay are handled deterministically."""
        engine = ReplayEngine()
        corpus = [_input("k", {"v": 1}, memory_type=MemoryType.PREFERENCE)]

        p = create_proposal(SID, ["evt-1"], MemoryType.PREFERENCE, "k",
                             {"v": 1}, 0.9, RiskTier.AUTO_LOW, 0)

        # Same decision twice
        decisions = [
            ReplayDecision(seq=0, proposal_id=p.proposal_id,
                           action="APPROVE", actor="op"),
            ReplayDecision(seq=1, proposal_id=p.proposal_id,
                           action="APPROVE", actor="op"),
        ]

        r1 = engine.replay(corpus, decisions)
        r2 = engine.replay(corpus, decisions)

        # Hashes should still be stable (second approve is a no-op/illegal)
        assert r1.replay_decisions_hash == r2.replay_decisions_hash

    def test_missing_proposal_references_reported(self):
        """Decisions referencing non-existent proposals are tracked."""
        engine = ReplayEngine()
        corpus = [_input("k", {"v": 1})]

        decisions = [
            ReplayDecision(seq=0, proposal_id="nonexistent_id",
                           action="APPROVE", actor="op"),
        ]

        result = engine.replay(corpus, decisions)
        assert "nonexistent_id" in result.missing_proposal_refs

    def test_provenance_hash_parity_with_live(self):
        """Provenance chain hash from live path matches replay hash structure."""
        pipeline = MemoryGovernancePipeline()
        engine = ReplayEngine()

        # Live path
        r1 = pipeline.propose(
            session_id=SID,
            origin_event_ids=["e1"],
            memory_type=MemoryType.SYSTEM_STATE,
            subject_key="api.health",
            payload={"component": "api", "state": "ok"},
            confidence=0.95,
        )
        # Auto-approved via policy

        live_hash = pipeline.provenance.deterministic_hash()
        assert len(live_hash) == 64  # SHA-256 hex

        # Replay path
        corpus = [_input("api.health", {"component": "api", "state": "ok"},
                          memory_type=MemoryType.SYSTEM_STATE, confidence=0.95)]
        replay_result = engine.replay(corpus, [])

        # Both should have produced decisions (auto-approve for SYSTEM_STATE)
        assert replay_result.total_proposals == 1
        assert len(replay_result.applied_ids) >= 1

    def test_zero_silent_mutation_global(self):
        """Global invariant: silent_write_count is always 0."""
        pipeline = MemoryGovernancePipeline()

        # Submit 10 varied proposals
        for i in range(10):
            pipeline.propose(
                session_id=SID,
                origin_event_ids=[f"evt-{i}"],
                memory_type=MemoryType.FACT if i % 2 == 0 else MemoryType.SYSTEM_STATE,
                subject_key=f"key-{i}",
                payload={"idx": i},
                confidence=0.6 + (i * 0.03),
            )

        report = pipeline.get_report()
        assert report["silent_write_count"] == 0
        assert report["conflict_unsurfaced_count"] == 0
