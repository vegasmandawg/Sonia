"""Append-only ledger storage with ACID guarantees."""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class LedgerStore:
    """Manages durable event ledger (append-only log)."""

    def __init__(self, db):
        """Initialize ledger store with database instance."""
        self.db = db
        self._table_name = "ledger_events"

    async def initialize(self) -> None:
        """Initialize ledger table if not exists."""
        logger.info("Initializing ledger store...")
        # Table creation happens in migrations
        logger.info("Ledger store initialized")

    async def append(self, event: Dict[str, Any]) -> str:
        """Append event to ledger. Returns event_id."""
        try:
            event_id = event.get("event_id")
            query = f"""
                INSERT INTO {self._table_name}
                (event_id, event_type, entity_id, timestamp, 
                 correlation_id, payload, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                event_id,
                event.get("event_type"),
                event.get("entity_id"),
                event.get("timestamp"),
                event.get("correlation_id"),
                json.dumps(event.get("payload", {})),
                event.get("signature", ""),
            )
            await self.db.execute(query, params)
            logger.debug(f"Event {event_id} appended to ledger")
            return event_id
        except Exception as e:
            logger.error(f"Failed to append to ledger: {e}")
            raise

    async def query(
        self,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query ledger with optional filters."""
        query = f"SELECT * FROM {self._table_name} WHERE 1=1"
        params = []

        if entity_id:
            query += " AND entity_id = ?"
            params.append(entity_id)

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)

        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        try:
            rows = await self.db.fetch(query, params)
            results = []
            for row in rows:
                results.append({
                    "event_id": row[0],
                    "event_type": row[1],
                    "entity_id": row[2],
                    "timestamp": row[3],
                    "correlation_id": row[4],
                    "payload": json.loads(row[5]),
                })
            return results
        except Exception as e:
            logger.error(f"Ledger query failed: {e}")
            raise

    async def count(self) -> int:
        """Count total ledger events."""
        try:
            result = await self.db.fetch(
                f"SELECT COUNT(*) FROM {self._table_name}"
            )
            return result[0][0] if result else 0
        except Exception as e:
            logger.error(f"Count query failed: {e}")
            return 0

    async def health(self) -> Dict[str, Any]:
        """Check ledger health."""
        try:
            count = await self.count()
            return {"status": "healthy", "events_count": count}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
