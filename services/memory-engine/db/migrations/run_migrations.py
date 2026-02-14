"""Run database migrations."""

import asyncio
import logging
from pathlib import Path
import aiosqlite

logger = logging.getLogger(__name__)


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    """Return True if a table exists in the current SQLite database."""
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    )
    row = await cursor.fetchone()
    return row is not None


async def _reconcile_chunk_tables(db: aiosqlite.Connection) -> None:
    """Normalize legacy document_chunks table to canonical workspace_chunks."""
    has_workspace = await _table_exists(db, "workspace_chunks")
    has_document = await _table_exists(db, "document_chunks")

    if has_document and not has_workspace:
        logger.info("Renaming legacy document_chunks table to workspace_chunks")
        await db.execute("ALTER TABLE document_chunks RENAME TO workspace_chunks")
        await db.commit()
        return

    if has_document and has_workspace:
        logger.info("Copying legacy document_chunks rows into workspace_chunks")
        await db.execute(
            """
            INSERT OR IGNORE INTO workspace_chunks
            (chunk_id, doc_id, content, chunk_index, start_offset, end_offset, embedding_id)
            SELECT chunk_id, doc_id, content, chunk_index, start_offset, end_offset, embedding_id
            FROM document_chunks
            """
        )
        await db.commit()


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

        await _reconcile_chunk_tables(db)
    
    logger.info("All migrations completed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    db_path = "S:\\data\\memory\\ledger.db"
    asyncio.run(run_migrations(db_path))
