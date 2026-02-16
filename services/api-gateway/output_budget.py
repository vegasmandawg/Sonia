"""
v3.7 M3 — Output Budget Enforcement

Centralised budget enforcement for all output paths.
Deterministic truncation with audit trail.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.output_budget")


class BudgetDimension(str, Enum):
    """Dimensions on which output budgets are enforced."""
    OUTPUT_CHARS = "output_chars"
    CONTEXT_CHARS = "context_chars"
    TOOL_CALLS = "tool_calls"
    VISION_FRAMES = "vision_frames"
    MEMORY_ENTRIES = "memory_entries"


class TruncationStrategy(str, Enum):
    """How to handle budget overflow."""
    HARD_CUT = "hard_cut"          # truncate at limit
    SENTENCE_BOUNDARY = "sentence_boundary"  # truncate at last sentence
    DROP_OLDEST = "drop_oldest"    # drop oldest items (for lists)
    REJECT = "reject"              # reject the operation entirely


@dataclass
class BudgetLimit:
    """A single budget limit configuration."""
    dimension: BudgetDimension
    max_value: int
    strategy: TruncationStrategy = TruncationStrategy.HARD_CUT
    warn_at_pct: float = 0.8  # warn when usage reaches this fraction

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "max_value": self.max_value,
            "strategy": self.strategy.value,
            "warn_at_pct": self.warn_at_pct,
        }


@dataclass
class BudgetResult:
    """Result of a budget enforcement check."""
    dimension: str
    original_size: int
    enforced_size: int
    truncated: bool
    strategy_used: str
    budget_remaining: int
    warn: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "original_size": self.original_size,
            "enforced_size": self.enforced_size,
            "truncated": self.truncated,
            "strategy_used": self.strategy_used,
            "budget_remaining": self.budget_remaining,
            "warn": self.warn,
        }


# ── Default Budget Configuration ────────────────────────────────────────────

DEFAULT_BUDGETS: Dict[str, BudgetLimit] = {
    BudgetDimension.OUTPUT_CHARS.value: BudgetLimit(
        dimension=BudgetDimension.OUTPUT_CHARS,
        max_value=4000,
        strategy=TruncationStrategy.SENTENCE_BOUNDARY,
    ),
    BudgetDimension.CONTEXT_CHARS.value: BudgetLimit(
        dimension=BudgetDimension.CONTEXT_CHARS,
        max_value=7000,
        strategy=TruncationStrategy.HARD_CUT,
    ),
    BudgetDimension.TOOL_CALLS.value: BudgetLimit(
        dimension=BudgetDimension.TOOL_CALLS,
        max_value=5,
        strategy=TruncationStrategy.REJECT,
    ),
    BudgetDimension.VISION_FRAMES.value: BudgetLimit(
        dimension=BudgetDimension.VISION_FRAMES,
        max_value=3,
        strategy=TruncationStrategy.DROP_OLDEST,
    ),
    BudgetDimension.MEMORY_ENTRIES.value: BudgetLimit(
        dimension=BudgetDimension.MEMORY_ENTRIES,
        max_value=10,
        strategy=TruncationStrategy.DROP_OLDEST,
    ),
}


class OutputBudgetEnforcer:
    """
    Enforces output budgets across all dimensions with deterministic
    truncation and audit trail.

    Key invariants:
    1. Every enforcement produces a BudgetResult for audit.
    2. Truncation is deterministic (same input -> same output).
    3. Budget limits are configurable per-dimension.
    4. Enforcement history is bounded.
    """

    def __init__(self, budgets: Optional[Dict[str, BudgetLimit]] = None):
        self._budgets = budgets or dict(DEFAULT_BUDGETS)
        self._enforcement_log: List[BudgetResult] = []
        self._max_log: int = 1000
        self._total_enforcements: int = 0
        self._total_truncations: int = 0

    def get_limit(self, dimension: str) -> Optional[BudgetLimit]:
        """Get the budget limit for a dimension."""
        return self._budgets.get(dimension)

    def set_limit(self, dimension: str, limit: BudgetLimit) -> None:
        """Update a budget limit."""
        self._budgets[dimension] = limit

    def enforce_text(
        self,
        text: str,
        dimension: str = BudgetDimension.OUTPUT_CHARS.value,
    ) -> tuple:
        """
        Enforce a character budget on text.

        Returns (enforced_text, BudgetResult).
        """
        limit = self._budgets.get(dimension)
        if limit is None:
            result = BudgetResult(
                dimension=dimension,
                original_size=len(text),
                enforced_size=len(text),
                truncated=False,
                strategy_used="none",
                budget_remaining=0,
            )
            self._record(result)
            return text, result

        original_size = len(text)
        max_val = limit.max_value
        warn = original_size >= int(max_val * limit.warn_at_pct)

        if original_size <= max_val:
            result = BudgetResult(
                dimension=dimension,
                original_size=original_size,
                enforced_size=original_size,
                truncated=False,
                strategy_used=limit.strategy.value,
                budget_remaining=max_val - original_size,
                warn=warn,
            )
            self._record(result)
            return text, result

        # Truncate
        if limit.strategy == TruncationStrategy.SENTENCE_BOUNDARY:
            enforced = self._truncate_sentence(text, max_val)
        elif limit.strategy == TruncationStrategy.REJECT:
            enforced = ""
        else:
            enforced = text[:max_val]

        result = BudgetResult(
            dimension=dimension,
            original_size=original_size,
            enforced_size=len(enforced),
            truncated=True,
            strategy_used=limit.strategy.value,
            budget_remaining=max(0, max_val - len(enforced)),
            warn=True,
        )
        self._total_truncations += 1
        self._record(result)
        return enforced, result

    def enforce_count(
        self,
        items: List[Any],
        dimension: str,
    ) -> tuple:
        """
        Enforce a count budget on a list of items.

        Returns (enforced_items, BudgetResult).
        """
        limit = self._budgets.get(dimension)
        if limit is None:
            result = BudgetResult(
                dimension=dimension,
                original_size=len(items),
                enforced_size=len(items),
                truncated=False,
                strategy_used="none",
                budget_remaining=0,
            )
            self._record(result)
            return items, result

        original_size = len(items)
        max_val = limit.max_value
        warn = original_size >= int(max_val * limit.warn_at_pct)

        if original_size <= max_val:
            result = BudgetResult(
                dimension=dimension,
                original_size=original_size,
                enforced_size=original_size,
                truncated=False,
                strategy_used=limit.strategy.value,
                budget_remaining=max_val - original_size,
                warn=warn,
            )
            self._record(result)
            return items, result

        # Truncate
        if limit.strategy == TruncationStrategy.DROP_OLDEST:
            enforced = items[-max_val:]
        elif limit.strategy == TruncationStrategy.REJECT:
            enforced = []
        else:
            enforced = items[:max_val]

        result = BudgetResult(
            dimension=dimension,
            original_size=original_size,
            enforced_size=len(enforced),
            truncated=True,
            strategy_used=limit.strategy.value,
            budget_remaining=max(0, max_val - len(enforced)),
            warn=True,
        )
        self._total_truncations += 1
        self._record(result)
        return enforced, result

    def _truncate_sentence(self, text: str, max_chars: int) -> str:
        """Truncate at the last sentence boundary within max_chars."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        # Find last sentence-ending punctuation
        for sep in [". ", "! ", "? ", ".\n", "!\n", "?\n"]:
            last_idx = truncated.rfind(sep)
            if last_idx > max_chars * 0.5:
                return truncated[:last_idx + 1].rstrip()
        return truncated.rstrip()

    def _record(self, result: BudgetResult) -> None:
        """Record enforcement result for audit."""
        self._total_enforcements += 1
        self._enforcement_log.append(result)
        if len(self._enforcement_log) > self._max_log:
            self._enforcement_log = self._enforcement_log[-self._max_log:]

    def get_enforcement_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent enforcement results."""
        return [r.to_dict() for r in self._enforcement_log[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        """Return enforcer statistics."""
        return {
            "total_enforcements": self._total_enforcements,
            "total_truncations": self._total_truncations,
            "configured_dimensions": list(self._budgets.keys()),
            "dimension_count": len(self._budgets),
        }

    def get_budget_table(self) -> List[Dict[str, Any]]:
        """Export all budget limits for operator review."""
        return [b.to_dict() for b in self._budgets.values()]
