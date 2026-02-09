"""Run database migrations."""

import asyncio
import logging
from pathlib import Path
import aiosqlite

logger = logging.getLogger(__name__)


async def run_migrations(db_path: str) -> None:
    """Run all migrations in order."""
    migration_dir = Path(__file__).parent
    migrations = sorted(migration_dir.glob("*.sql"))
    
    async with aiosqlite.connect(db_path) as db:
        for migration_file in migrations:
            logger.info(f"Running migration: {migration_file.name}")
            with open(migration_file, 'r') as f:
                sql = f.read()
                await db.executescript(sql)
            await db.commit()
    
    logger.info("All migrations completed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_path = "S:\\data\\memory\\ledger.db"
    asyncio.run(run_migrations(db_path))
