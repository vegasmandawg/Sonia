"""Burst-safe confirmation batching with provenance linkage.

Batches perception events for confirmation while preserving:
    - Deterministic batch ordering
    - Explicit batch TTL
    - One confirmation token per actionable item
    - Trace links from coalesced items to all contributing events
    - No bypass under load (throttle intake, never auto-approve)

Contract:
    - stable_batch_key for deterministic ordering
    - explicit batch_ttl for expiry
    - deterministic split/merge on replay
    - backpressure via throttle, never by skipping gates
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .event_normalizer import PerceptionEnvelope


# ── Constants ────────────────────────────────────────────────────────────

MAX_PENDING_CONFIRMATIONS = 50    # contractual limit
DEFAULT_BATCH_TTL_EVENTS = 20    # batch closes after N events (deterministic)
MAX_BATCH_SIZE = 10              # max items per batch


# ── Confirmation Item ────────────────────────────────────────────────────

@dataclass
class ConfirmationItem:
    """Single actionable item requiring confirmation.

    Links back to all contributing perception events via source_event_ids.
    """
    item_id: str
    action: str                           # recommended action
    source_event_ids: List[str]           # all contributing events (trace links)
    primary_event_id: str                 # highest-confidence contributor
    confidence: float
    priority: int
    session_id: str
    correlation_id: str
    batch_key: str                        # deterministic batch assignment

    # Status tracking
    status: str = "pending"               # pending | confirmed | denied | expired
    consumed: bool = False                # one-shot flag


# ── Batch ────────────────────────────────────────────────────────────────

@dataclass
class ConfirmationBatch:
    """Group of confirmation items with deterministic ordering."""
    batch_id: str
    batch_key: str                        # stable ordering key
    items: List[ConfirmationItem] = field(default_factory=list)
    events_since_open: int = 0            # TTL counter (event-based, not wall-clock)
    closed: bool = False

    @property
    def size(self) -> int:
        return len(self.items)

    @property
    def pending_count(self) -> int:
        return sum(1 for i in self.items if i.status == "pending")


# ── Batcher ──────────────────────────────────────────────────────────────

class ConfirmationBatcher:
    """Burst-safe confirmation batcher.

    Invariants:
        1. Total pending items <= MAX_PENDING_CONFIRMATIONS
        2. One-shot confirmation consumption
        3. No auto-approve under load
        4. Deterministic batch assignment and ordering
        5. All coalesced items retain trace links to contributing events
    """

    def __init__(
        self,
        max_pending: int = MAX_PENDING_CONFIRMATIONS,
        batch_ttl_events: int = DEFAULT_BATCH_TTL_EVENTS,
        max_batch_size: int = MAX_BATCH_SIZE,
    ):
        self._max_pending = max_pending
        self._batch_ttl_events = batch_ttl_events
        self._max_batch_size = max_batch_size

        self._batches: OrderedDict[str, ConfirmationBatch] = OrderedDict()
        self._items: Dict[str, ConfirmationItem] = {}  # item_id -> item
        self._item_seq = 0
        self._batch_seq = 0

        self._stats = {
            "total_submitted": 0,
            "total_confirmed": 0,
            "total_denied": 0,
            "total_expired": 0,
            "total_throttled": 0,
            "double_consume_attempts": 0,
            "bypass_attempts": 0,
        }

    @property
    def pending_count(self) -> int:
        return sum(1 for i in self._items.values() if i.status == "pending")

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def batch_count(self) -> int:
        return len(self._batches)

    def submit(
        self,
        envelope: PerceptionEnvelope,
        priority: int,
        action: str,
    ) -> Tuple[Optional[ConfirmationItem], Optional[str]]:
        """Submit an event for confirmation.

        Returns (item, throttle_reason).
        If throttled, item is None and throttle_reason explains why.
        Never auto-approves or bypasses -- throttle is the only degradation.
        """
        self._stats["total_submitted"] += 1

        # ── Backpressure check ────────────────────────────────────────
        if self.pending_count >= self._max_pending:
            self._stats["total_throttled"] += 1
            return None, f"throttled: pending={self.pending_count} >= max={self._max_pending}"

        # ── Find or create batch ──────────────────────────────────────
        batch_key = self._compute_batch_key(envelope)
        batch = self._get_or_create_batch(batch_key)

        # Close batch if full or TTL exceeded
        if batch.size >= self._max_batch_size or batch.events_since_open >= self._batch_ttl_events:
            batch.closed = True
            batch = self._get_or_create_batch(batch_key)

        # ── Create confirmation item ──────────────────────────────────
        self._item_seq += 1
        item_id = f"ci_{self._item_seq:06d}"

        item = ConfirmationItem(
            item_id=item_id,
            action=action,
            source_event_ids=[envelope.event_id],
            primary_event_id=envelope.event_id,
            confidence=envelope.confidence,
            priority=priority,
            session_id=envelope.session_id,
            correlation_id=envelope.correlation_id,
            batch_key=batch_key,
        )

        batch.items.append(item)
        batch.events_since_open += 1
        self._items[item_id] = item

        return item, None

    def add_trace_link(self, item_id: str, contributing_event_id: str) -> bool:
        """Add a contributing event trace link to an existing item.

        Used when coalesced events map to the same confirmation item.
        Returns True if link added, False if item not found.
        """
        item = self._items.get(item_id)
        if not item:
            return False
        if contributing_event_id not in item.source_event_ids:
            item.source_event_ids.append(contributing_event_id)
        return True

    def confirm(self, item_id: str) -> Dict[str, Any]:
        """Confirm (approve) an item. One-shot: cannot confirm twice.

        Returns result dict with status.
        """
        item = self._items.get(item_id)
        if not item:
            return {"ok": False, "status": "not_found", "item_id": item_id}

        if item.consumed:
            self._stats["double_consume_attempts"] += 1
            return {
                "ok": False,
                "status": "already_consumed",
                "item_id": item_id,
                "double_consume": True,
            }

        if item.status != "pending":
            return {"ok": False, "status": item.status, "item_id": item_id}

        item.status = "confirmed"
        item.consumed = True
        self._stats["total_confirmed"] += 1
        return {"ok": True, "status": "confirmed", "item_id": item_id}

    def deny(self, item_id: str, reason: str = "") -> Dict[str, Any]:
        """Deny an item. One-shot: cannot deny after confirm."""
        item = self._items.get(item_id)
        if not item:
            return {"ok": False, "status": "not_found", "item_id": item_id}

        if item.consumed:
            self._stats["double_consume_attempts"] += 1
            return {
                "ok": False,
                "status": "already_consumed",
                "item_id": item_id,
                "double_consume": True,
            }

        if item.status != "pending":
            return {"ok": False, "status": item.status, "item_id": item_id}

        item.status = "denied"
        item.consumed = True
        self._stats["total_denied"] += 1
        return {"ok": True, "status": "denied", "item_id": item_id, "reason": reason}

    def validate_execution(self, item_id: str) -> Dict[str, Any]:
        """Validate an item is confirmed before execution.

        Raises no exceptions -- returns result dict.
        Tracks bypass attempts for audit.
        """
        item = self._items.get(item_id)
        if not item:
            self._stats["bypass_attempts"] += 1
            return {"ok": False, "status": "not_found", "bypass_attempt": True}

        if item.status != "confirmed":
            self._stats["bypass_attempts"] += 1
            return {
                "ok": False,
                "status": item.status,
                "bypass_attempt": True,
                "item_id": item_id,
            }

        return {"ok": True, "status": "confirmed", "item_id": item_id}

    def expire_stale(self, max_age_events: int = 200) -> int:
        """Expire old pending items based on event count since submission.

        Returns count of expired items.
        Uses event count (deterministic) not wall-clock.
        """
        expired = 0
        current_seq = self._item_seq
        for item in self._items.values():
            if item.status == "pending" and not item.consumed:
                # Extract seq from item_id
                try:
                    item_seq = int(item.item_id.split("_")[1])
                except (IndexError, ValueError):
                    continue
                if current_seq - item_seq > max_age_events:
                    item.status = "expired"
                    item.consumed = True
                    self._stats["total_expired"] += 1
                    expired += 1
        return expired

    def get_pending(self, session_id: Optional[str] = None) -> List[ConfirmationItem]:
        """Get all pending items, optionally filtered by session."""
        return [
            i for i in self._items.values()
            if i.status == "pending"
            and (session_id is None or i.session_id == session_id)
        ]

    def get_orphan_count(self) -> int:
        """Count orphaned items (consumed but not in final state).

        Should always be 0 after drain. Non-zero indicates a bug.
        """
        return sum(
            1 for i in self._items.values()
            if i.consumed and i.status == "pending"
        )

    def _compute_batch_key(self, envelope: PerceptionEnvelope) -> str:
        """Deterministic batch key from stable envelope fields."""
        parts = [envelope.session_id, envelope.source, envelope.event_type]
        canonical = "|".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def _get_or_create_batch(self, batch_key: str) -> ConfirmationBatch:
        """Get open batch for key, or create new one."""
        # Find existing open batch
        for batch in self._batches.values():
            if batch.batch_key == batch_key and not batch.closed:
                return batch

        # Create new batch
        self._batch_seq += 1
        batch_id = f"batch_{self._batch_seq:06d}"
        batch = ConfirmationBatch(batch_id=batch_id, batch_key=batch_key)
        self._batches[batch_id] = batch
        return batch

    def clear(self) -> None:
        """Reset all state."""
        self._batches.clear()
        self._items.clear()
        self._item_seq = 0
        self._batch_seq = 0
        self._stats = {
            "total_submitted": 0,
            "total_confirmed": 0,
            "total_denied": 0,
            "total_expired": 0,
            "total_throttled": 0,
            "double_consume_attempts": 0,
            "bypass_attempts": 0,
        }
