"""Replay Determinism Policy — v4.2 E2.

Enforces that DLQ replay operations are deterministic and idempotent.
Distinguishes dry-run from live replay contracts.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set

SCHEMA_VERSION = "1.0.0"


class ReplayMode(Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


class ReplayOutcome(Enum):
    SUCCESS = "success"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    FAILED_VALIDATION = "failed_validation"
    FAILED_EXECUTION = "failed_execution"


@dataclass(frozen=True)
class DLQEntry:
    """A dead-letter queue entry for replay."""
    entry_id: str
    original_action: str
    payload_hash: str
    failure_class: str
    attempt_count: int
    namespace: str

    def __post_init__(self):
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        if not self.original_action:
            raise ValueError("original_action must be non-empty")
        if self.attempt_count < 0:
            raise ValueError("attempt_count must be non-negative")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "entry_id": self.entry_id,
            "original_action": self.original_action,
            "payload_hash": self.payload_hash,
            "failure_class": self.failure_class,
            "attempt_count": self.attempt_count,
            "namespace": self.namespace,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass
class ReplayResult:
    """Result of a single replay attempt."""
    entry_id: str
    mode: ReplayMode
    outcome: ReplayOutcome
    side_effects: bool  # True only for live successful replays
    detail: str

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "entry_id": self.entry_id,
            "mode": self.mode.value,
            "outcome": self.outcome.value,
            "side_effects": self.side_effects,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


class ReplayDeterminismPolicy:
    """Enforces deterministic, idempotent DLQ replay."""

    def __init__(self):
        self._replayed_ids: Set[str] = set()
        self._replay_log: List[ReplayResult] = []

    def evaluate_replay(self, entry: DLQEntry, mode: ReplayMode) -> ReplayResult:
        """Evaluate a replay request deterministically.

        Dry-run: validates but never produces side effects.
        Live: executes but skips duplicates (idempotent).
        """
        # Idempotency: skip if already replayed in live mode
        if mode == ReplayMode.LIVE and entry.entry_id in self._replayed_ids:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                outcome=ReplayOutcome.SKIPPED_DUPLICATE,
                side_effects=False,
                detail="Already replayed — idempotent skip",
            )
            self._replay_log.append(result)
            return result

        # Validate entry
        if not entry.payload_hash:
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                outcome=ReplayOutcome.FAILED_VALIDATION,
                side_effects=False,
                detail="Missing payload_hash",
            )
            self._replay_log.append(result)
            return result

        if mode == ReplayMode.DRY_RUN:
            # Dry-run: validate only, no side effects, no idempotency tracking
            result = ReplayResult(
                entry_id=entry.entry_id,
                mode=mode,
                outcome=ReplayOutcome.SUCCESS,
                side_effects=False,
                detail="Dry-run validation passed",
            )
            self._replay_log.append(result)
            return result

        # Live replay
        self._replayed_ids.add(entry.entry_id)
        result = ReplayResult(
            entry_id=entry.entry_id,
            mode=mode,
            outcome=ReplayOutcome.SUCCESS,
            side_effects=True,
            detail="Live replay executed",
        )
        self._replay_log.append(result)
        return result

    def check_dry_run_contract(self, result: ReplayResult) -> dict:
        """Verify dry-run contract: never side effects."""
        if result.mode != ReplayMode.DRY_RUN:
            return {"valid": False, "reason": "not_a_dry_run"}
        return {
            "valid": not result.side_effects,
            "reason": "no_side_effects" if not result.side_effects else "side_effects_detected",
        }

    def check_live_contract(self, result: ReplayResult) -> dict:
        """Verify live contract: side effects only on success."""
        if result.mode != ReplayMode.LIVE:
            return {"valid": False, "reason": "not_a_live_replay"}
        if result.outcome == ReplayOutcome.SUCCESS:
            return {"valid": result.side_effects, "reason": "success_with_side_effects"}
        return {"valid": not result.side_effects, "reason": "no_side_effects_on_non_success"}

    def check_idempotency(self, entry_id: str) -> bool:
        """Check if an entry has already been replayed."""
        return entry_id in self._replayed_ids

    @property
    def replay_log(self) -> List[ReplayResult]:
        return list(self._replay_log)

    @property
    def replayed_count(self) -> int:
        return len(self._replayed_ids)
