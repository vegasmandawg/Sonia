"""
Unit tests for migration_policy.py — MigrationPolicyEngine.

Covers:
- Migration registration
- Graph validation (topological sort, cycles, missing deps, orphans)
- Decision logic (apply, skip, block)
- Idempotency enforcement
- Dependency ordering
- Rollback strategy tracking
- Stats and decision log
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"S:\services\memory-engine")

from migration_policy import (
    Migration,
    MigrationPolicyEngine,
    MigrationState,
    RollbackStrategy,
    MigrationGraphValidation,
    MigrationDecision,
)


def _engine_with_chain() -> MigrationPolicyEngine:
    """Create engine with a linear chain: v1 -> v2 -> v3."""
    engine = MigrationPolicyEngine()
    engine.register(Migration(version="v1", description="Initial schema"))
    engine.register(Migration(version="v2", description="Add index", depends_on=["v1"]))
    engine.register(Migration(version="v3", description="Add column", depends_on=["v2"]))
    return engine


class TestMigrationPolicyEngine:
    """Tests for MigrationPolicyEngine."""

    def test_register_migration(self):
        engine = MigrationPolicyEngine()
        m = Migration(version="v1", description="test")
        engine.register(m)
        stats = engine.get_stats()
        assert stats["total_registered"] == 1

    def test_valid_linear_graph(self):
        engine = _engine_with_chain()
        result = engine.validate_graph()
        assert result.valid is True
        assert result.total_migrations == 3
        # v1 must come before v2, v2 before v3
        order = result.execution_order
        assert order.index("v1") < order.index("v2") < order.index("v3")

    def test_cycle_detection(self):
        engine = MigrationPolicyEngine()
        engine.register(Migration(version="a", description="A", depends_on=["b"]))
        engine.register(Migration(version="b", description="B", depends_on=["a"]))
        result = engine.validate_graph()
        assert result.valid is False
        assert len(result.cycles) > 0

    def test_missing_dependency(self):
        engine = MigrationPolicyEngine()
        engine.register(Migration(version="v1", description="test", depends_on=["v0"]))
        result = engine.validate_graph()
        assert result.valid is False
        assert len(result.missing_deps) > 0
        assert result.missing_deps[0] == ("v1", "v0")

    def test_orphan_detection(self):
        engine = MigrationPolicyEngine()
        engine.register(Migration(version="v1", description="Main", depends_on=[]))
        engine.register(Migration(version="v2", description="Dep on v1", depends_on=["v1"]))
        engine.register(Migration(version="orphan", description="No connections"))
        result = engine.validate_graph()
        assert "orphan" in result.orphans

    def test_decide_apply(self):
        engine = _engine_with_chain()
        decision = engine.decide("v1")
        assert decision.action == "apply"
        assert "not yet applied" in decision.reason.lower()

    def test_decide_block_missing_dependency(self):
        engine = _engine_with_chain()
        decision = engine.decide("v2")  # v1 not applied yet
        assert decision.action == "block"
        assert "v1" in decision.reason

    def test_decide_skip_idempotent(self):
        engine = _engine_with_chain()
        engine.mark_applied("v1")
        decision = engine.decide("v1")
        assert decision.action == "skip"
        assert "idempotent" in decision.reason.lower()

    def test_decide_block_non_idempotent_rerun(self):
        engine = MigrationPolicyEngine()
        engine.register(Migration(version="v1", description="test", idempotent=False))
        engine.mark_applied("v1")
        decision = engine.decide("v1")
        assert decision.action == "block"
        assert "not idempotent" in decision.reason.lower()

    def test_decide_block_unknown_migration(self):
        engine = MigrationPolicyEngine()
        decision = engine.decide("nonexistent")
        assert decision.action == "block"
        assert "not registered" in decision.reason.lower()

    def test_get_pending_returns_unapplied(self):
        engine = _engine_with_chain()
        engine.mark_applied("v1")
        pending = engine.get_pending()
        assert "v1" not in pending
        assert "v2" in pending
        assert "v3" in pending

    def test_get_pending_respects_order(self):
        engine = _engine_with_chain()
        pending = engine.get_pending()
        assert pending.index("v1") < pending.index("v2") < pending.index("v3")

    def test_get_pending_empty_on_invalid_graph(self):
        engine = MigrationPolicyEngine()
        engine.register(Migration(version="a", description="A", depends_on=["b"]))
        engine.register(Migration(version="b", description="B", depends_on=["a"]))
        assert engine.get_pending() == []

    def test_decision_log(self):
        engine = _engine_with_chain()
        engine.decide("v1")
        engine.decide("v2")
        log = engine.get_decision_log()
        assert len(log) == 2
        assert log[0]["version"] == "v1"
        assert log[1]["version"] == "v2"

    def test_stats(self):
        engine = _engine_with_chain()
        engine.mark_applied("v1")
        stats = engine.get_stats()
        assert stats["total_registered"] == 3
        assert stats["total_applied"] == 1
        assert stats["total_pending"] == 2
        assert stats["idempotent_count"] == 3  # all default to True

    def test_rollback_strategy_default(self):
        m = Migration(version="v1", description="test")
        assert m.rollback_strategy == RollbackStrategy.RESTORE_FROM_BACKUP

    def test_rollback_strategy_forward_only(self):
        m = Migration(version="v1", description="test", rollback_strategy=RollbackStrategy.FORWARD_ONLY)
        engine = MigrationPolicyEngine()
        engine.register(m)
        decision = engine.decide("v1")
        assert decision.rollback_strategy == "forward_only"

    def test_graph_validation_to_dict(self):
        engine = _engine_with_chain()
        result = engine.validate_graph()
        d = result.to_dict()
        assert "valid" in d
        assert "execution_order" in d
        assert "cycles" in d

    def test_decision_to_dict(self):
        engine = _engine_with_chain()
        decision = engine.decide("v1")
        d = decision.to_dict()
        assert d["version"] == "v1"
        assert d["action"] == "apply"
        assert "idempotent" in d

    def test_diamond_dependency(self):
        """v1 -> v2a, v1 -> v2b, v2a+v2b -> v3."""
        engine = MigrationPolicyEngine()
        engine.register(Migration(version="v1", description="base"))
        engine.register(Migration(version="v2a", description="branch a", depends_on=["v1"]))
        engine.register(Migration(version="v2b", description="branch b", depends_on=["v1"]))
        engine.register(Migration(version="v3", description="merge", depends_on=["v2a", "v2b"]))
        result = engine.validate_graph()
        assert result.valid is True
        order = result.execution_order
        assert order.index("v1") < order.index("v2a")
        assert order.index("v1") < order.index("v2b")
        assert order.index("v2a") < order.index("v3")
        assert order.index("v2b") < order.index("v3")

    def test_decide_after_full_chain_applied(self):
        engine = _engine_with_chain()
        engine.mark_applied("v1")
        engine.mark_applied("v2")
        decision = engine.decide("v3")
        assert decision.action == "apply"
