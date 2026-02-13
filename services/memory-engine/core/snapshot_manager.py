"""Snapshot management for context optimization."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Manages memory snapshots for context optimization."""

    def __init__(self, snapshot_dir: str, db):
        """Initialize snapshot manager."""
        self.snapshot_dir = Path(snapshot_dir)
        self.db = db
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Initialize snapshot manager."""
        logger.info(f"Snapshot manager initialized: {self.snapshot_dir}")

    async def create(self, session_id: str) -> str:
        """Create snapshot of current memory state."""
        try:
            snapshot_id = str(uuid4())
            timestamp = datetime.utcnow().isoformat()
            
            # Collect actual memory state from database
            ledger_events = []
            try:
                with self.db.connection() as conn:
                    rows = conn.execute(
                        "SELECT id, type, content, created_at FROM ledger "
                        "WHERE archived_at IS NULL ORDER BY created_at DESC LIMIT 1000"
                    ).fetchall()
                    ledger_events = [
                        {"id": r["id"], "type": r["type"],
                         "content": r["content"][:200], "created_at": r["created_at"]}
                        for r in rows
                    ]
            except Exception as e:
                logger.warning(f"Could not fetch ledger events for snapshot: {e}")

            active_count = 0
            try:
                with self.db.connection() as conn:
                    row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM ledger WHERE archived_at IS NULL"
                    ).fetchone()
                    active_count = row["cnt"] if row else 0
            except Exception as e:
                logger.warning(f"Could not count memories for snapshot: {e}")

            snapshot_data = {
                "snapshot_id": snapshot_id,
                "session_id": session_id,
                "created_at": timestamp,
                "ledger_events": ledger_events,
                "active_memory_count": active_count,
                "documents": [],
                "vector_count": 0,
            }
            
            # Write to file
            snapshot_file = (
                self.snapshot_dir / f"{timestamp.replace(':', '-')}_"
                f"{session_id}.json"
            )
            
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot_data, f, indent=2)
            
            logger.info(f"Snapshot created: {snapshot_id}")
            return snapshot_id
            
        except Exception as e:
            logger.error(f"Snapshot creation failed: {e}")
            raise

    async def restore(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore memory from snapshot."""
        try:
            # Find snapshot file containing snapshot_id
            for snapshot_file in self.snapshot_dir.glob("*.json"):
                with open(snapshot_file, 'r') as f:
                    data = json.load(f)
                    if data.get("snapshot_id") == snapshot_id:
                        logger.info(f"Snapshot restored: {snapshot_id}")
                        return data
            
            raise ValueError(f"Snapshot not found: {snapshot_id}")
            
        except Exception as e:
            logger.error(f"Snapshot restore failed: {e}")
            raise

    async def count(self) -> int:
        """Count total snapshots."""
        try:
            return len(list(self.snapshot_dir.glob("*.json")))
        except Exception as e:
            logger.error(f"Count failed: {e}")
            return 0

    async def shutdown(self) -> None:
        """Shutdown snapshot manager."""
        logger.info("Snapshot manager shutdown")
