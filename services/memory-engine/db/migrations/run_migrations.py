"""Run memory-engine database migrations."""

import argparse
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "memory.db"
MIGRATION_TABLE = "schema_migrations"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Return True if a table exists in the current SQLite database."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _reconcile_chunk_tables(conn: sqlite3.Connection) -> None:
    """Normalize legacy document_chunks table to canonical workspace_chunks."""
    has_workspace = _table_exists(conn, "workspace_chunks")
    has_document = _table_exists(conn, "document_chunks")

    if has_document and not has_workspace:
        logger.info("Renaming legacy document_chunks table to workspace_chunks")
        conn.execute("ALTER TABLE document_chunks RENAME TO workspace_chunks")
        conn.commit()
        return

    if has_document and has_workspace:
        logger.info("Copying legacy document_chunks rows into workspace_chunks")
        conn.execute(
            """
            INSERT OR IGNORE INTO workspace_chunks
            (chunk_id, doc_id, content, chunk_index, start_offset, end_offset, embedding_id)
            SELECT chunk_id, doc_id, content, chunk_index, start_offset, end_offset, embedding_id
            FROM document_chunks
            """
        )
        conn.commit()


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_applied(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(f"SELECT name FROM {MIGRATION_TABLE}").fetchall()
    return {row[0] for row in rows}


def _list_migrations(migration_dir: Path) -> List[Path]:
    # Only include numbered migration files.
    return sorted(migration_dir.glob("[0-9][0-9][0-9]_*.sql"))


def run_migrations_sync(db_path: str | Path) -> None:
    """Run all unapplied SQL migrations in deterministic order."""
    migration_dir = Path(__file__).parent
    migrations = _list_migrations(migration_dir)
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Running migrations against %s", target)

    conn = sqlite3.connect(str(target))
    try:
        _ensure_migration_table(conn)
        applied = _load_applied(conn)

        for migration_file in migrations:
            name = migration_file.name
            if name in applied:
                continue

            logger.info("Applying migration: %s", name)
            sql = migration_file.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                f"INSERT INTO {MIGRATION_TABLE} (name, applied_at) VALUES (?, ?)",
                (name, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        _reconcile_chunk_tables(conn)
    finally:
        conn.close()

    logger.info("Migrations complete")


async def run_migrations(db_path: str) -> None:
    """Async wrapper for compatibility with existing callers."""
    await asyncio.to_thread(run_migrations_sync, db_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Run memory-engine DB migrations")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    run_migrations_sync(args.db_path)
