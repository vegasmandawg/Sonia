"""Deterministic perception event dedupe engine.

Contract:
    decision = engine.evaluate(envelope)
    - Every evaluation produces an auditable DedupeDecision
    - Same envelope stream always produces same decisions (deterministic)
    - Window-bounded: old entries expire based on event count, not wall-clock

Decisions:
    DROP_DUPLICATE: exact duplicate within window, dropped with audit
    COALESCE: near-duplicate, merged with reference to parent
    ACCEPT: unique event, passed through for routing

Provenance:
    Every decision emits a DedupeDecision record with:
    - decision, reason_code, dedupe_key, window_id, parent_event_id
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .event_normalizer import PerceptionEnvelope


# ── Decision types ───────────────────────────────────────────────────────

DECISION_DROP = "DROP_DUPLICATE"
DECISION_COALESCE = "COALESCE"
DECISION_ACCEPT = "ACCEPT"


@dataclass(frozen=True)
class DedupeDecision:
    """Auditable dedupe decision with full provenance."""
    decision: str                         # DROP_DUPLICATE | COALESCE | ACCEPT
    reason_code: str                      # human-readable reason
    dedupe_key: str                       # key that matched (or new)
    window_id: str                        # dedupe window identifier
    event_id: str                         # incoming event ID
    parent_event_id: Optional[str] = None # if coalesced, the parent we merged into
    confidence_delta: float = 0.0         # confidence difference (for near-dup)


@dataclass
class DedupeEntry:
    """Internal tracking entry in the dedupe window."""
    event_id: str
    dedupe_key: str
    content_hash: str
    object_id: str
    confidence: float
    spatial_token: Optional[str]
    source: str
    seq: int                              # insertion order


# ── Near-duplicate detection ─────────────────────────────────────────────

def _is_near_duplicate(
    entry: DedupeEntry,
    envelope: PerceptionEnvelope,
) -> bool:
    """Check if envelope is a near-duplicate of an existing entry.

    Near-duplicate = same object_id + same source + different content_hash
    but within spatial proximity (same spatial_token) or confidence is close.
    """
    if entry.object_id != envelope.object_id:
        return False
    if entry.source != envelope.source:
        return False
    # Same content hash = exact dup (handled separately)
    if entry.content_hash == envelope.content_hash:
        return False
    # Spatial proximity (vision)
    if entry.spatial_token and envelope.spatial_token:
        if entry.spatial_token == envelope.spatial_token:
            return True
    # Confidence proximity (within 0.15)
    if abs(entry.confidence - envelope.confidence) < 0.15:
        return True
    return False


# ── Engine ───────────────────────────────────────────────────────────────

class DedupeEngine:
    """Deterministic, window-bounded perception event dedupe.

    Uses event-count-based windowing (not wall-clock) for determinism.
    """

    def __init__(self, window_size: int = 100):
        """Initialize with fixed window size (event count).

        Args:
            window_size: max entries in dedupe window before oldest evicted.
        """
        self._window_size = window_size
        self._window_id = "dedupe-window-0"
        self._entries: OrderedDict[str, DedupeEntry] = OrderedDict()
        self._seq = 0
        self._decisions: List[DedupeDecision] = []
        self._stats = {
            "total_evaluated": 0,
            "total_dropped": 0,
            "total_coalesced": 0,
            "total_accepted": 0,
        }

    @property
    def window_size(self) -> int:
        return self._window_size

    @property
    def window_count(self) -> int:
        return len(self._entries)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def decisions(self) -> List[DedupeDecision]:
        """All decisions made (for audit/replay verification)."""
        return list(self._decisions)

    def evaluate(self, envelope: PerceptionEnvelope) -> DedupeDecision:
        """Evaluate an envelope for deduplication.

        Returns a DedupeDecision (always). Deterministic for same input stream.
        """
        self._stats["total_evaluated"] += 1
        key = envelope.dedupe_key

        # ── Exact duplicate check ─────────────────────────────────────
        if key in self._entries:
            existing = self._entries[key]
            decision = DedupeDecision(
                decision=DECISION_DROP,
                reason_code="exact_dedupe_key_match",
                dedupe_key=key,
                window_id=self._window_id,
                event_id=envelope.event_id,
                parent_event_id=existing.event_id,
            )
            self._stats["total_dropped"] += 1
            self._decisions.append(decision)
            return decision

        # ── Near-duplicate check (scan window) ────────────────────────
        for existing_key, existing in self._entries.items():
            if _is_near_duplicate(existing, envelope):
                decision = DedupeDecision(
                    decision=DECISION_COALESCE,
                    reason_code="near_duplicate_coalesce",
                    dedupe_key=key,
                    window_id=self._window_id,
                    event_id=envelope.event_id,
                    parent_event_id=existing.event_id,
                    confidence_delta=abs(existing.confidence - envelope.confidence),
                )
                # Update entry with higher confidence version
                if envelope.confidence > existing.confidence:
                    self._entries[existing_key] = DedupeEntry(
                        event_id=envelope.event_id,
                        dedupe_key=existing_key,
                        content_hash=envelope.content_hash,
                        object_id=envelope.object_id,
                        confidence=envelope.confidence,
                        spatial_token=envelope.spatial_token,
                        source=envelope.source,
                        seq=self._seq,
                    )
                self._seq += 1
                self._stats["total_coalesced"] += 1
                self._decisions.append(decision)
                return decision

        # ── Unique: accept ────────────────────────────────────────────
        self._seq += 1
        entry = DedupeEntry(
            event_id=envelope.event_id,
            dedupe_key=key,
            content_hash=envelope.content_hash,
            object_id=envelope.object_id,
            confidence=envelope.confidence,
            spatial_token=envelope.spatial_token,
            source=envelope.source,
            seq=self._seq,
        )

        # Evict oldest if window full
        if len(self._entries) >= self._window_size:
            self._entries.popitem(last=False)

        self._entries[key] = entry

        decision = DedupeDecision(
            decision=DECISION_ACCEPT,
            reason_code="unique_event",
            dedupe_key=key,
            window_id=self._window_id,
            event_id=envelope.event_id,
        )
        self._stats["total_accepted"] += 1
        self._decisions.append(decision)
        return decision

    def clear(self) -> None:
        """Clear all state. Used for testing or session reset."""
        self._entries.clear()
        self._decisions.clear()
        self._seq = 0
        self._stats = {
            "total_evaluated": 0,
            "total_dropped": 0,
            "total_coalesced": 0,
            "total_accepted": 0,
        }

    def replay_decisions_hash(self) -> str:
        """Deterministic hash of all decisions for replay verification."""
        import hashlib
        import json
        records = [
            {
                "decision": d.decision,
                "reason_code": d.reason_code,
                "dedupe_key": d.dedupe_key,
                "event_id": d.event_id,
                "parent_event_id": d.parent_event_id,
            }
            for d in self._decisions
        ]
        canonical = json.dumps(records, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
