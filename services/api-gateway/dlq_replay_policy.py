"""
v3.7 M2 — DLQ Replay Decision Policy

Deterministic replay decisions with dry-run/real-run traceability.
Incident bundle completeness extended with correlation lineage.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.dlq_replay_policy")


class ReplayDecision(str, Enum):
    """Possible outcomes of a replay decision."""
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


class RejectReason(str, Enum):
    """Reasons a replay can be rejected."""
    ALREADY_REPLAYED = "already_replayed"
    CIRCUIT_STILL_OPEN = "circuit_still_open"
    FAILURE_CLASS_NON_RETRYABLE = "failure_class_non_retryable"
    COOLDOWN_ACTIVE = "cooldown_active"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MANUAL_BLOCK = "manual_block"


# Non-retryable failure classes (from retry_taxonomy)
NON_RETRYABLE_CLASSES = frozenset({
    "circuit_open",
    "policy_denied",
    "validation_failed",
})


@dataclass
class ReplayTrace:
    """Full traceability for a replay decision."""
    letter_id: str
    decision: str
    dry_run: bool
    original_error_code: str
    original_failure_class: str
    correlation_id: str
    session_id: str = ""
    reject_reason: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    replay_correlation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "letter_id": self.letter_id,
            "decision": self.decision,
            "dry_run": self.dry_run,
            "original_error_code": self.original_error_code,
            "original_failure_class": self.original_failure_class,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }
        if self.session_id:
            d["session_id"] = self.session_id
        if self.reject_reason:
            d["reject_reason"] = self.reject_reason
        if self.replay_correlation_id:
            d["replay_correlation_id"] = self.replay_correlation_id
        return d


@dataclass
class CorrelationLineage:
    """Tracks the full lineage of an action through DLQ replay."""
    original_correlation_id: str
    original_action_id: str
    replay_correlation_ids: List[str] = field(default_factory=list)
    replay_action_ids: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, replayed, failed, abandoned

    def add_replay(self, correlation_id: str, action_id: str) -> None:
        self.replay_correlation_ids.append(correlation_id)
        self.replay_action_ids.append(action_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_correlation_id": self.original_correlation_id,
            "original_action_id": self.original_action_id,
            "replay_count": len(self.replay_correlation_ids),
            "replay_correlation_ids": self.replay_correlation_ids,
            "replay_action_ids": self.replay_action_ids,
            "status": self.status,
        }


class DLQReplayPolicyEngine:
    """
    Makes deterministic replay decisions for dead letters.

    Policy rules:
    1. Already-replayed letters are rejected (idempotent).
    2. Non-retryable failure classes are rejected unless overridden.
    3. Replay cooldown prevents storm replays.
    4. Replay budget limits total replays per window.
    5. Dry-run never mutates state.
    """

    def __init__(
        self,
        replay_cooldown_seconds: float = 30.0,
        max_replays_per_window: int = 20,
        window_seconds: float = 300.0,
    ):
        self._cooldown_s = replay_cooldown_seconds
        self._max_replays = max_replays_per_window
        self._window_s = window_seconds
        self._replay_times: List[float] = []
        self._last_replay: Dict[str, float] = {}  # letter_id -> timestamp
        self._traces: List[ReplayTrace] = []
        self._lineages: Dict[str, CorrelationLineage] = {}
        self._blocked_letters: set = set()

    def evaluate(
        self,
        letter_id: str,
        already_replayed: bool,
        failure_class: str,
        error_code: str,
        correlation_id: str,
        dry_run: bool = True,
        session_id: str = "",
        breaker_state: str = "closed",
    ) -> ReplayTrace:
        """
        Evaluate whether a dead letter should be replayed.

        Returns a ReplayTrace with the decision and reasoning.
        """
        # 1. Idempotency: already replayed
        if already_replayed:
            return self._make_trace(
                letter_id, ReplayDecision.REJECT, dry_run,
                error_code, failure_class, correlation_id, session_id,
                reject_reason=RejectReason.ALREADY_REPLAYED.value,
            )

        # 2. Manual block
        if letter_id in self._blocked_letters:
            return self._make_trace(
                letter_id, ReplayDecision.REJECT, dry_run,
                error_code, failure_class, correlation_id, session_id,
                reject_reason=RejectReason.MANUAL_BLOCK.value,
            )

        # 3. Non-retryable failure class
        if failure_class in NON_RETRYABLE_CLASSES:
            return self._make_trace(
                letter_id, ReplayDecision.REJECT, dry_run,
                error_code, failure_class, correlation_id, session_id,
                reject_reason=RejectReason.FAILURE_CLASS_NON_RETRYABLE.value,
            )

        # 4. Circuit still open
        if breaker_state == "open":
            return self._make_trace(
                letter_id, ReplayDecision.DEFER, dry_run,
                error_code, failure_class, correlation_id, session_id,
                reject_reason=RejectReason.CIRCUIT_STILL_OPEN.value,
            )

        # 5. Per-letter cooldown
        now = time.monotonic()
        last = self._last_replay.get(letter_id, 0)
        if now - last < self._cooldown_s:
            return self._make_trace(
                letter_id, ReplayDecision.DEFER, dry_run,
                error_code, failure_class, correlation_id, session_id,
                reject_reason=RejectReason.COOLDOWN_ACTIVE.value,
            )

        # 6. Window budget
        cutoff = now - self._window_s
        self._replay_times = [t for t in self._replay_times if t > cutoff]
        if len(self._replay_times) >= self._max_replays:
            return self._make_trace(
                letter_id, ReplayDecision.DEFER, dry_run,
                error_code, failure_class, correlation_id, session_id,
                reject_reason=RejectReason.BUDGET_EXHAUSTED.value,
            )

        # All checks pass: approve
        if not dry_run:
            self._last_replay[letter_id] = now
            self._replay_times.append(now)

        return self._make_trace(
            letter_id, ReplayDecision.APPROVE, dry_run,
            error_code, failure_class, correlation_id, session_id,
        )

    def block_letter(self, letter_id: str) -> None:
        """Manually block a letter from replay."""
        self._blocked_letters.add(letter_id)

    def unblock_letter(self, letter_id: str) -> None:
        """Remove manual block from a letter."""
        self._blocked_letters.discard(letter_id)

    def record_lineage(
        self,
        original_correlation_id: str,
        original_action_id: str,
        replay_correlation_id: str = "",
        replay_action_id: str = "",
    ) -> CorrelationLineage:
        """Record or update correlation lineage for an action."""
        key = original_action_id
        if key not in self._lineages:
            self._lineages[key] = CorrelationLineage(
                original_correlation_id=original_correlation_id,
                original_action_id=original_action_id,
            )
        lineage = self._lineages[key]
        if replay_correlation_id:
            lineage.add_replay(replay_correlation_id, replay_action_id)
            lineage.status = "replayed"
        return lineage

    def get_lineage(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Get correlation lineage for an action."""
        lineage = self._lineages.get(action_id)
        return lineage.to_dict() if lineage else None

    def _make_trace(
        self,
        letter_id: str,
        decision: ReplayDecision,
        dry_run: bool,
        error_code: str,
        failure_class: str,
        correlation_id: str,
        session_id: str = "",
        reject_reason: str = "",
    ) -> ReplayTrace:
        trace = ReplayTrace(
            letter_id=letter_id,
            decision=decision.value,
            dry_run=dry_run,
            original_error_code=error_code,
            original_failure_class=failure_class,
            correlation_id=correlation_id,
            session_id=session_id,
            reject_reason=reject_reason,
        )
        self._traces.append(trace)
        if len(self._traces) > 1000:
            self._traces = self._traces[-1000:]
        return trace

    def get_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent replay traces."""
        return [t.to_dict() for t in self._traces[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        now = time.monotonic()
        cutoff = now - self._window_s
        recent = sum(1 for t in self._replay_times if t > cutoff)
        return {
            "total_traces": len(self._traces),
            "replays_in_window": recent,
            "max_replays_per_window": self._max_replays,
            "blocked_letters": len(self._blocked_letters),
            "tracked_lineages": len(self._lineages),
        }
