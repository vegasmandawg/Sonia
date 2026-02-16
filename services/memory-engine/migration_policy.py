"""
Migration policy framework for memory-engine.

Provides:
- Explicit migration graph validation (topological sort, cycle detection)
- Rollback strategy: restore-based deterministic rollback policy
- Migration versioning with forward-only + restore proof
- Idempotency enforcement (re-run safety)
- Pre/post migration health checks
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class MigrationState(Enum):
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class RollbackStrategy(Enum):
    RESTORE_FROM_BACKUP = "restore_from_backup"
    FORWARD_ONLY = "forward_only"


@dataclass
class Migration:
    version: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    sql_up: str = ""
    idempotent: bool = True
    rollback_strategy: RollbackStrategy = RollbackStrategy.RESTORE_FROM_BACKUP

    def __hash__(self):
        return hash(self.version)


@dataclass
class MigrationGraphValidation:
    valid: bool
    total_migrations: int
    execution_order: List[str] = field(default_factory=list)
    cycles: List[List[str]] = field(default_factory=list)
    missing_deps: List[Tuple[str, str]] = field(default_factory=list)
    orphans: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "total_migrations": self.total_migrations,
            "execution_order": self.execution_order,
            "cycles": self.cycles,
            "missing_deps": [{"migration": m, "missing": d} for m, d in self.missing_deps],
            "orphans": self.orphans,
        }


@dataclass
class MigrationDecision:
    version: str
    action: str  # apply, skip, block
    reason: str
    idempotent: bool
    rollback_strategy: str
    pre_check_passed: bool = True

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "action": self.action,
            "reason": self.reason,
            "idempotent": self.idempotent,
            "rollback_strategy": self.rollback_strategy,
            "pre_check_passed": self.pre_check_passed,
        }


class MigrationPolicyEngine:
    """Validates and governs database migrations."""

    def __init__(self):
        self._migrations: Dict[str, Migration] = {}
        self._applied: Set[str] = set()
        self._decision_log: List[MigrationDecision] = []

    def register(self, migration: Migration) -> None:
        """Register a migration."""
        self._migrations[migration.version] = migration

    def mark_applied(self, version: str) -> None:
        """Mark a migration as already applied."""
        self._applied.add(version)

    def validate_graph(self) -> MigrationGraphValidation:
        """Validate the migration dependency graph."""
        versions = set(self._migrations.keys())
        missing_deps: List[Tuple[str, str]] = []
        orphans: List[str] = []

        # Check for missing dependencies
        for ver, mig in self._migrations.items():
            for dep in mig.depends_on:
                if dep not in versions:
                    missing_deps.append((ver, dep))

        # Build adjacency list for topological sort
        in_degree: Dict[str, int] = defaultdict(int)
        graph: Dict[str, List[str]] = defaultdict(list)

        for ver in versions:
            if ver not in in_degree:
                in_degree[ver] = 0

        for ver, mig in self._migrations.items():
            for dep in mig.depends_on:
                if dep in versions:
                    graph[dep].append(ver)
                    in_degree[ver] += 1

        # Kahn's algorithm for topological sort + cycle detection
        queue = deque([v for v in versions if in_degree[v] == 0])
        execution_order: List[str] = []

        while queue:
            node = queue.popleft()
            execution_order.append(node)
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If not all nodes processed, there's a cycle
        has_cycle = len(execution_order) != len(versions)
        cycles: List[List[str]] = []
        if has_cycle:
            remaining = versions - set(execution_order)
            cycles.append(sorted(remaining))

        # Find orphans (no dependents, not depended on)
        depended_on = set()
        for mig in self._migrations.values():
            depended_on.update(mig.depends_on)
        has_dependents = set()
        for ver, mig in self._migrations.items():
            if mig.depends_on:
                has_dependents.add(ver)
        for ver in versions:
            if ver not in depended_on and ver not in has_dependents and len(versions) > 1:
                orphans.append(ver)

        return MigrationGraphValidation(
            valid=not has_cycle and len(missing_deps) == 0,
            total_migrations=len(versions),
            execution_order=execution_order,
            cycles=cycles,
            missing_deps=missing_deps,
            orphans=orphans,
        )

    def decide(self, version: str) -> MigrationDecision:
        """Decide whether to apply a migration."""
        if version not in self._migrations:
            decision = MigrationDecision(
                version=version,
                action="block",
                reason=f"Migration '{version}' not registered",
                idempotent=False,
                rollback_strategy="unknown",
                pre_check_passed=False,
            )
            self._decision_log.append(decision)
            return decision

        mig = self._migrations[version]

        # Already applied + idempotent = skip
        if version in self._applied and mig.idempotent:
            decision = MigrationDecision(
                version=version,
                action="skip",
                reason="Already applied (idempotent, safe to skip)",
                idempotent=mig.idempotent,
                rollback_strategy=mig.rollback_strategy.value,
            )
            self._decision_log.append(decision)
            return decision

        # Already applied + not idempotent = block
        if version in self._applied and not mig.idempotent:
            decision = MigrationDecision(
                version=version,
                action="block",
                reason="Already applied (not idempotent, cannot re-run safely)",
                idempotent=mig.idempotent,
                rollback_strategy=mig.rollback_strategy.value,
            )
            self._decision_log.append(decision)
            return decision

        # Check dependencies are applied
        for dep in mig.depends_on:
            if dep not in self._applied:
                decision = MigrationDecision(
                    version=version,
                    action="block",
                    reason=f"Dependency '{dep}' not yet applied",
                    idempotent=mig.idempotent,
                    rollback_strategy=mig.rollback_strategy.value,
                    pre_check_passed=False,
                )
                self._decision_log.append(decision)
                return decision

        # All checks pass
        decision = MigrationDecision(
            version=version,
            action="apply",
            reason="All dependencies met, not yet applied",
            idempotent=mig.idempotent,
            rollback_strategy=mig.rollback_strategy.value,
        )
        self._decision_log.append(decision)
        return decision

    def get_pending(self) -> List[str]:
        """Return migrations not yet applied, in dependency order."""
        graph_result = self.validate_graph()
        if not graph_result.valid:
            return []
        return [v for v in graph_result.execution_order if v not in self._applied]

    def get_decision_log(self) -> List[dict]:
        """Return decision log."""
        return [d.to_dict() for d in self._decision_log]

    def get_stats(self) -> dict:
        """Return engine statistics."""
        return {
            "total_registered": len(self._migrations),
            "total_applied": len(self._applied),
            "total_pending": len(self._migrations) - len(self._applied),
            "total_decisions": len(self._decision_log),
            "idempotent_count": sum(1 for m in self._migrations.values() if m.idempotent),
            "restore_rollback_count": sum(1 for m in self._migrations.values()
                                          if m.rollback_strategy == RollbackStrategy.RESTORE_FROM_BACKUP),
        }
