"""Priority routing with queue discipline for perception events.

Routes accepted (deduplicated) events into policy-defined lanes:
    P0: safety-critical (immediate processing)
    P1: action-blocking / high-confidence (standard processing)
    P2: informational (deferred processing)

Scheduling: strict P0 preemption, weighted round-robin for P1/P2.
Overflow: never silent drop -- auditable overflow decisions.

Contract:
    - Deterministic lane assignment from event properties
    - Deterministic ordering within each lane
    - Bounded queues with explicit overflow policy
    - Every overflow emits an audit record
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .event_normalizer import PerceptionEnvelope


# ── Priority Levels ──────────────────────────────────────────────────────

PRIORITY_P0 = 0  # safety-critical
PRIORITY_P1 = 1  # action-blocking
PRIORITY_P2 = 2  # informational

PRIORITY_NAMES = {PRIORITY_P0: "P0_SAFETY", PRIORITY_P1: "P1_ACTION", PRIORITY_P2: "P2_INFO"}

# ── Lane assignment rules ────────────────────────────────────────────────

# Event types that are always P0 (safety-critical)
P0_EVENT_TYPES = frozenset({"safety_alert", "emergency", "privacy_violation"})

# Event types that are always P2 (informational)
P2_EVENT_TYPES = frozenset({"ambient_update", "background_change"})

# High confidence threshold for P1 promotion
HIGH_CONFIDENCE_THRESHOLD = 0.8


def assign_priority(envelope: PerceptionEnvelope) -> int:
    """Deterministic priority assignment from envelope properties.

    Rules (in order):
        1. P0 if event_type in safety-critical set
        2. P2 if event_type in informational set
        3. P1 if confidence >= HIGH_CONFIDENCE_THRESHOLD or has recommended_action
        4. P2 otherwise
    """
    if envelope.event_type in P0_EVENT_TYPES:
        return PRIORITY_P0

    if envelope.event_type in P2_EVENT_TYPES:
        return PRIORITY_P2

    # Check for recommended action in payload
    has_action = bool(envelope.payload.get("recommended_action"))
    if envelope.confidence >= HIGH_CONFIDENCE_THRESHOLD or has_action:
        return PRIORITY_P1

    return PRIORITY_P2


# ── Overflow record ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class OverflowRecord:
    """Audit record for queue overflow decisions."""
    event_id: str
    priority: int
    priority_name: str
    reason: str                           # "queue_cap_exceeded"
    queue_size_at_overflow: int
    queue_cap: int
    action_taken: str                     # "coalesce_lowest" | "reject_with_audit"


# ── Router ───────────────────────────────────────────────────────────────

class PriorityRouter:
    """Deterministic priority router with bounded lanes.

    Invariants:
        - Never silently drops events
        - All overflow decisions are auditable
        - Same input stream always produces same lane state
    """

    DEFAULT_LANE_CAP = 50  # per lane

    def __init__(
        self,
        lane_cap: int = DEFAULT_LANE_CAP,
        total_cap: int = 150,
    ):
        self._lane_cap = lane_cap
        self._total_cap = total_cap
        self._lanes: Dict[int, deque] = {
            PRIORITY_P0: deque(),
            PRIORITY_P1: deque(),
            PRIORITY_P2: deque(),
        }
        self._overflow_log: List[OverflowRecord] = []
        self._stats = {
            "total_routed": 0,
            "total_overflow": 0,
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": 0,
        }
        self._seq = 0

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def overflow_log(self) -> List[OverflowRecord]:
        return list(self._overflow_log)

    @property
    def total_queued(self) -> int:
        return sum(len(lane) for lane in self._lanes.values())

    def lane_size(self, priority: int) -> int:
        return len(self._lanes.get(priority, deque()))

    def route(self, envelope: PerceptionEnvelope) -> Tuple[int, Optional[OverflowRecord]]:
        """Route an accepted envelope into a priority lane.

        Returns (priority, overflow_record_or_None).
        """
        priority = assign_priority(envelope)
        lane = self._lanes[priority]
        overflow = None

        self._stats["total_routed"] += 1

        # Check lane cap
        if len(lane) >= self._lane_cap:
            overflow = self._handle_overflow(envelope, priority)
        # Check total cap
        elif self.total_queued >= self._total_cap:
            overflow = self._handle_overflow(envelope, priority)
        else:
            self._seq += 1
            lane.append((self._seq, envelope))
            self._stats[f"p{priority}_count"] += 1

        return priority, overflow

    def drain(self, max_items: int = 10) -> List[Tuple[int, PerceptionEnvelope]]:
        """Drain items in priority order (P0 first, then weighted P1/P2).

        Returns list of (priority, envelope) tuples.
        Deterministic: same queue state produces same drain order.
        """
        result: List[Tuple[int, PerceptionEnvelope]] = []

        # P0 always drained first (preemption)
        while self._lanes[PRIORITY_P0] and len(result) < max_items:
            _, env = self._lanes[PRIORITY_P0].popleft()
            result.append((PRIORITY_P0, env))

        # Weighted round-robin for P1/P2 (3:1 ratio)
        p1_weight = 3
        p2_weight = 1
        cycle = 0

        while len(result) < max_items and (self._lanes[PRIORITY_P1] or self._lanes[PRIORITY_P2]):
            # P1 gets 3 turns per P2 turn
            if cycle % (p1_weight + p2_weight) < p1_weight:
                target = PRIORITY_P1
            else:
                target = PRIORITY_P2

            if self._lanes[target]:
                _, env = self._lanes[target].popleft()
                result.append((target, env))
            elif self._lanes[PRIORITY_P1 if target == PRIORITY_P2 else PRIORITY_P2]:
                # Fallback to other lane if target empty
                other = PRIORITY_P1 if target == PRIORITY_P2 else PRIORITY_P2
                _, env = self._lanes[other].popleft()
                result.append((other, env))

            cycle += 1

        return result

    def _handle_overflow(
        self,
        envelope: PerceptionEnvelope,
        priority: int,
    ) -> OverflowRecord:
        """Handle overflow: coalesce lowest priority first, never silent drop."""
        # Try to evict from lowest priority lane first
        for evict_priority in [PRIORITY_P2, PRIORITY_P1]:
            if evict_priority > priority and self._lanes[evict_priority]:
                self._lanes[evict_priority].popleft()
                self._seq += 1
                self._lanes[priority].append((self._seq, envelope))
                self._stats[f"p{priority}_count"] += 1

                record = OverflowRecord(
                    event_id=envelope.event_id,
                    priority=priority,
                    priority_name=PRIORITY_NAMES[priority],
                    reason="queue_cap_exceeded",
                    queue_size_at_overflow=self.total_queued,
                    queue_cap=self._total_cap,
                    action_taken="coalesce_lowest",
                )
                self._overflow_log.append(record)
                self._stats["total_overflow"] += 1
                return record

        # Cannot evict -- reject with full audit
        record = OverflowRecord(
            event_id=envelope.event_id,
            priority=priority,
            priority_name=PRIORITY_NAMES[priority],
            reason="queue_cap_exceeded",
            queue_size_at_overflow=self.total_queued,
            queue_cap=self._total_cap,
            action_taken="reject_with_audit",
        )
        self._overflow_log.append(record)
        self._stats["total_overflow"] += 1
        return record

    def clear(self) -> None:
        """Reset all state."""
        for lane in self._lanes.values():
            lane.clear()
        self._overflow_log.clear()
        self._seq = 0
        self._stats = {
            "total_routed": 0,
            "total_overflow": 0,
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": 0,
        }
