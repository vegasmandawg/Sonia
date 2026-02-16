"""
Replay policy: DLQ dry-run vs live-run semantics, idempotency invariants.

Provides clear contracts for how DLQ replay differs between dry-run
and live execution modes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ReplayMode(Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class ReplayVerdict(Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    SKIP = "SKIP"


@dataclass(frozen=True)
class DLQEntry:
    """A dead-letter queue entry for replay consideration."""
    entry_id: str
    action_type: str
    payload_hash: str
    failure_class: str
    retry_count: int
    correlation_id: str
    timestamp: str
    payload: Optional[Dict[str, Any]] = None

    def fingerprint(self) -> str:
        canonical = f"{self.entry_id}|{self.action_type}|{self.payload_hash}|{self.failure_class}"
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class ReplayResult:
    entry_id: str
    mode: ReplayMode
    verdict: ReplayVerdict
    side_effects: List[str]
    detail: str = ""


# -- Replay contracts --

RETRYABLE_FAILURE_CLASSES = frozenset([
    "CONNECTION_BOOTSTRAP",
    "TIMEOUT",
    "EXECUTION_ERROR",
    "BACKPRESSURE",
])

NON_RETRYABLE_FAILURE_CLASSES = frozenset([
    "CIRCUIT_OPEN",
    "POLICY_DENIED",
    "VALIDATION_FAILED",
    "UNKNOWN",
])

ALL_FAILURE_CLASSES = RETRYABLE_FAILURE_CLASSES | NON_RETRYABLE_FAILURE_CLASSES


class ReplayPolicyEngine:
    """Evaluates DLQ entries for replay eligibility with mode-aware semantics."""

    def __init__(self, max_retry_count: int = 3):
        self._max_retry_count = max_retry_count
        self._replay_log: List[ReplayResult] = []

    def evaluate(self, entry: DLQEntry, mode: ReplayMode) -> ReplayResult:
        """Evaluate a DLQ entry for replay."""
        # Non-retryable classes are always rejected
        if entry.failure_class in NON_RETRYABLE_FAILURE_CLASSES:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                verdict=ReplayVerdict.REJECT,
                side_effects=[],
                detail=f"failure class '{entry.failure_class}' is non-retryable",
            )
            self._replay_log.append(result)
            return result

        # Check retry budget
        if entry.retry_count >= self._max_retry_count:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                verdict=ReplayVerdict.REJECT,
                side_effects=[],
                detail=f"retry count {entry.retry_count} exceeds max {self._max_retry_count}",
            )
            self._replay_log.append(result)
            return result

        # Unknown failure class
        if entry.failure_class not in ALL_FAILURE_CLASSES:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                verdict=ReplayVerdict.REJECT,
                side_effects=[],
                detail=f"unrecognized failure class '{entry.failure_class}'",
            )
            self._replay_log.append(result)
            return result

        # Mode-specific semantics
        if mode == ReplayMode.DRY_RUN:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                verdict=ReplayVerdict.ACCEPT,
                side_effects=[],  # DRY_RUN: zero side effects
                detail="dry-run: validated without execution",
            )
        else:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                verdict=ReplayVerdict.ACCEPT,
                side_effects=["action_executed", "dlq_entry_consumed", "audit_logged"],
                detail="live: replay executed with side effects",
            )

        self._replay_log.append(result)
        return result

    def get_replay_log(self) -> List[ReplayResult]:
        return list(self._replay_log)

    def clear_log(self) -> None:
        self._replay_log.clear()


def dry_run_differs_from_live(entry: DLQEntry, engine: ReplayPolicyEngine) -> bool:
    """Verify that dry-run and live semantics produce different side effects."""
    dry = engine.evaluate(entry, ReplayMode.DRY_RUN)
    live = engine.evaluate(entry, ReplayMode.LIVE)
    # For accepted entries, side effects must differ
    if dry.verdict == ReplayVerdict.ACCEPT and live.verdict == ReplayVerdict.ACCEPT:
        return dry.side_effects != live.side_effects
    # For rejected entries, both should have no side effects
    return dry.side_effects == live.side_effects == []


def replay_is_idempotent_in_dry_run(entry: DLQEntry, engine: ReplayPolicyEngine) -> bool:
    """Verify dry-run produces identical results on repeated evaluation."""
    r1 = engine.evaluate(entry, ReplayMode.DRY_RUN)
    r2 = engine.evaluate(entry, ReplayMode.DRY_RUN)
    return (
        r1.verdict == r2.verdict
        and r1.side_effects == r2.side_effects
        and r1.detail == r2.detail
    )
