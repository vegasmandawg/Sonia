"""Provenance tracking for memory items.

Records the source and derivation chain for each memory entry.
Uses the audit_log table for persistent tracking and an in-memory
index for fast lookups.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProvenanceTracker:
    """Tracks provenance for all memory items."""

    def __init__(self, db):
        """Initialize provenance tracker.

        Args:
            db: MemoryDatabase instance (sync, existing)
        """
        self.db = db
        self._index: Dict[str, Dict[str, Any]] = {}  # memory_id -> provenance

    def track(
        self,
        memory_id: str,
        source_type: str = "direct",
        source_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Record provenance for a memory item.

        Args:
            memory_id: The memory entry being tracked
            source_type: How this memory was created (direct, chunk, summary, tool_event, etc.)
            source_id: Parent document/memory ID if derived
            metadata: Additional provenance metadata (offsets, confidence, etc.)
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            record = {
                "memory_id": memory_id,
                "source_type": source_type,
                "source_id": source_id,
                "metadata": metadata or {},
                "tracked_at": now,
            }

            # Persist to audit_log
            with self.db.connection() as conn:
                import json
                conn.execute(
                    """
                    INSERT INTO audit_log (id, operation, ledger_id, details, performed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"prov_{uuid.uuid4().hex[:12]}",
                        "PROVENANCE",
                        memory_id,
                        json.dumps(record),
                        now,
                    ),
                )
                conn.commit()

            # Update in-memory index
            self._index[memory_id] = record
            logger.debug("Provenance tracked: %s source=%s", memory_id, source_type)

        except Exception as e:
            logger.error("Provenance tracking failed for %s: %s", memory_id, e)

    def get_provenance(self, memory_id: str) -> Dict[str, Any]:
        """Get provenance for a memory item.

        Checks in-memory index first, then falls back to DB query.
        """
        # Fast path: in-memory
        if memory_id in self._index:
            return self._index[memory_id]

        # Slow path: DB query
        try:
            import json
            with self.db.connection() as conn:
                row = conn.execute(
                    """
                    SELECT details FROM audit_log
                    WHERE ledger_id = ? AND operation = 'PROVENANCE'
                    ORDER BY performed_at DESC
                    LIMIT 1
                    """,
                    (memory_id,),
                ).fetchone()

            if row:
                details = row["details"] if hasattr(row, "keys") else row[0]
                record = json.loads(details) if details else {}
                self._index[memory_id] = record
                return record

        except Exception as e:
            logger.error("Provenance lookup failed for %s: %s", memory_id, e)

        return {}

    def get_chain(self, memory_id: str, max_depth: int = 10) -> List[Dict[str, Any]]:
        """Get the full provenance chain for a memory item.

        Follows source_id links up to max_depth.
        """
        chain = []
        current_id = memory_id

        for _ in range(max_depth):
            record = self.get_provenance(current_id)
            if not record:
                break
            chain.append(record)
            parent = record.get("source_id")
            if not parent or parent == current_id:
                break
            current_id = parent

        return chain

    def track_perception(
        self,
        memory_id: str,
        scene_id: str,
        correlation_id: str,
        trigger: str,
        model_used: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Track provenance for a perception-derived memory.

        Validates that all 4 required perception fields are non-empty.
        Calls track() with source_type="perception", source_id=scene_id.

        Raises:
            ValueError: if any required field is empty
        """
        for name, val in [("scene_id", scene_id), ("correlation_id", correlation_id),
                          ("trigger", trigger), ("model_used", model_used)]:
            if not val or not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"Perception provenance requires non-empty '{name}', got: {val!r}"
                )

        extra = metadata or {}
        extra.update({
            "scene_id": scene_id,
            "correlation_id": correlation_id,
            "trigger": trigger,
            "model_used": model_used,
        })

        self.track(
            memory_id=memory_id,
            source_type="perception",
            source_id=scene_id,
            metadata=extra,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return provenance tracking statistics."""
        return {
            "cached_records": len(self._index),
            "source_types": list(set(
                r.get("source_type", "unknown") for r in self._index.values()
            )),
        }
