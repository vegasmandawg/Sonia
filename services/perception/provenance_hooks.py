"""Provenance hooks for perception pipeline audit trail.

Every dedupe/routing/confirmation decision emits a provenance record.
Records are append-only and deterministic for replay verification.

Used by G20/G21 gate checks to verify:
    - Zero false bypass
    - Complete decision chain
    - Deterministic replay hash
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .dedupe_engine import DedupeDecision
from .priority_router import OverflowRecord


@dataclass(frozen=True)
class ProvenanceRecord:
    """Single audit record in the perception provenance chain."""
    record_type: str                      # dedupe | route | confirm | overflow
    event_id: str
    session_id: str
    decision: str                         # ACCEPT | DROP | COALESCE | ROUTE | CONFIRM | DENY | THROTTLE | OVERFLOW
    reason_code: str
    details: Dict[str, Any] = field(default_factory=dict)


class ProvenanceChain:
    """Append-only provenance chain for perception pipeline audit.

    Deterministic: same event stream produces same chain and hash.
    """

    def __init__(self):
        self._records: List[ProvenanceRecord] = []
        self._stats = {
            "total_records": 0,
            "dedupe_records": 0,
            "route_records": 0,
            "confirm_records": 0,
            "overflow_records": 0,
        }

    @property
    def records(self) -> List[ProvenanceRecord]:
        return list(self._records)

    @property
    def stats(self) -> Dict[str, int]:
        return dict(self._stats)

    @property
    def record_count(self) -> int:
        return len(self._records)

    def record_dedupe(
        self,
        decision: DedupeDecision,
        session_id: str,
    ) -> None:
        """Record a dedupe decision."""
        rec = ProvenanceRecord(
            record_type="dedupe",
            event_id=decision.event_id,
            session_id=session_id,
            decision=decision.decision,
            reason_code=decision.reason_code,
            details={
                "dedupe_key": decision.dedupe_key,
                "window_id": decision.window_id,
                "parent_event_id": decision.parent_event_id,
                "confidence_delta": decision.confidence_delta,
            },
        )
        self._records.append(rec)
        self._stats["total_records"] += 1
        self._stats["dedupe_records"] += 1

    def record_route(
        self,
        event_id: str,
        session_id: str,
        priority: int,
        priority_name: str,
    ) -> None:
        """Record a routing decision."""
        rec = ProvenanceRecord(
            record_type="route",
            event_id=event_id,
            session_id=session_id,
            decision="ROUTE",
            reason_code=f"assigned_to_{priority_name}",
            details={"priority": priority, "priority_name": priority_name},
        )
        self._records.append(rec)
        self._stats["total_records"] += 1
        self._stats["route_records"] += 1

    def record_overflow(
        self,
        overflow: OverflowRecord,
        session_id: str,
    ) -> None:
        """Record an overflow decision."""
        rec = ProvenanceRecord(
            record_type="overflow",
            event_id=overflow.event_id,
            session_id=session_id,
            decision="OVERFLOW",
            reason_code=overflow.reason,
            details={
                "priority": overflow.priority,
                "action_taken": overflow.action_taken,
                "queue_size": overflow.queue_size_at_overflow,
                "queue_cap": overflow.queue_cap,
            },
        )
        self._records.append(rec)
        self._stats["total_records"] += 1
        self._stats["overflow_records"] += 1

    def record_confirm(
        self,
        event_id: str,
        session_id: str,
        item_id: str,
        decision: str,
        reason: str = "",
    ) -> None:
        """Record a confirmation decision (submit/confirm/deny/throttle)."""
        rec = ProvenanceRecord(
            record_type="confirm",
            event_id=event_id,
            session_id=session_id,
            decision=decision,
            reason_code=reason or decision.lower(),
            details={"item_id": item_id},
        )
        self._records.append(rec)
        self._stats["total_records"] += 1
        self._stats["confirm_records"] += 1

    def deterministic_hash(self) -> str:
        """SHA-256 hash of the full provenance chain for replay verification.

        Deterministic: same event stream always produces same hash.
        """
        chain = [
            {
                "record_type": r.record_type,
                "event_id": r.event_id,
                "session_id": r.session_id,
                "decision": r.decision,
                "reason_code": r.reason_code,
            }
            for r in self._records
        ]
        canonical = json.dumps(chain, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def false_bypass_count(self) -> int:
        """Count events that reached confirmation without a dedupe decision.

        Should always be 0. Non-zero = G20 failure.
        """
        dedupe_event_ids = {
            r.event_id for r in self._records if r.record_type == "dedupe"
        }
        confirm_event_ids = {
            r.event_id for r in self._records
            if r.record_type == "confirm" and r.decision in ("SUBMIT", "CONFIRM")
        }
        # Events that got confirmed without going through dedupe
        bypassed = confirm_event_ids - dedupe_event_ids
        return len(bypassed)

    def clear(self) -> None:
        """Reset all records."""
        self._records.clear()
        self._stats = {
            "total_records": 0,
            "dedupe_records": 0,
            "route_records": 0,
            "confirm_records": 0,
            "overflow_records": 0,
        }
