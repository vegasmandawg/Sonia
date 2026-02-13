"""SQLite database wrapper for Memory Engine."""

import aiosqlite
import logging
from pathlib import Path
from typing import Any, List, Tuple

logger = logging.getLogger(__name__)


class SqliteDB:
    """Async SQLite database wrapper."""

    def __init__(self, db_path: str = "S:\\data\\memory\\ledger.db"):
        """Initialize SQLite database."""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None

    async def initialize(self) -> None:
        """Connect and initialize database."""
        try:
            self.conn = await aiosqlite.connect(str(self.db_path))
            await self.conn.execute("PRAGMA journal_mode = WAL")
            await self.conn.commit()
            logger.info(f"SQLite initialized: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite: {e}")
            raise

    async def execute(
        self, query: str, params: Tuple[Any, ...] = ()
    ) -> None:
        """Execute query (INSERT, UPDATE, DELETE)."""
        if not self.conn:
            raise RuntimeError("Database not initialized")
        
        try:
            await self.conn.execute(query, params)
            await self.conn.commit()
        except Exception as e:
            logger.error(f"Execute failed: {e}")
            raise

    async def fetch(
        self, query: str, params: List[Any] = None
    ) -> List[Tuple[Any, ...]]:
        """Fetch query results."""
        if not self.conn:
            raise RuntimeError("Database not initialized")
        
        try:
            params = params or []
            cursor = await self.conn.execute(query, params)
            rows = await cursor.fetchall()
            return rows
        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            raise

    async def size_mb(self) -> float:
        """Get database size in MB."""
        try:
            return self.db_path.stat().st_size / (1024 * 1024)
        except Exception as e:
            logger.error(f"Size check failed: {e}")
            return 0.0

    async def health(self) -> dict:
        """Check database health."""
        try:
            await self.conn.execute("SELECT 1")
            return {"status": "healthy"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    async def shutdown(self) -> None:
        """Shutdown database connection."""
        if self.conn:
            await self.conn.close()
            logger.info("SQLite connection closed")
