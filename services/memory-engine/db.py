"""
Memory Engine Database Module

SQLite-backed persistence for the Sonia memory system.
Provides CRUD operations with audit logging and schema versioning.
"""

import sqlite3
import json
import uuid
import logging
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

logger = logging.getLogger('memory-engine.db')

# Default database path
DB_PATH = Path(__file__).parent.parent.parent / "data" / "memory.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"
MIGRATION_RUNNER_PATH = Path(__file__).parent / "db" / "migrations" / "run_migrations.py"


class MemoryDatabase:
    """SQLite-backed memory store with ACID guarantees."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection."""
        self.db_path = db_path or str(DB_PATH)
        self._init_db()
    
    def _init_db(self):
        """Initialize database and schema."""
        logger.info(f"Initializing database: {self.db_path}")
        
        # Create parent directories
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Load and execute schema
        if SCHEMA_PATH.exists():
            with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
                schema = f.read()
            
            with self.connection() as conn:
                conn.executescript(schema)
                conn.commit()
            
            logger.info("Database schema initialized")
        else:
            logger.warning(f"Schema file not found: {SCHEMA_PATH}")

        # Apply incremental SQL migrations (idempotent, tracked).
        self._apply_migrations()

    def _apply_migrations(self):
        """Apply SQL migrations via local migration runner."""
        if not MIGRATION_RUNNER_PATH.exists():
            logger.warning(f"Migration runner not found: {MIGRATION_RUNNER_PATH}")
            return

        try:
            spec = importlib.util.spec_from_file_location(
                "_memory_migration_runner",
                MIGRATION_RUNNER_PATH,
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("Failed to load migration runner module spec")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            run_sync = getattr(module, "run_migrations_sync", None)
            if not callable(run_sync):
                raise RuntimeError("Migration runner missing run_migrations_sync")

            run_sync(self.db_path)
            logger.info("Database migrations applied")
        except Exception as e:
            logger.error(f"Database migration failed: {e}")
            raise
    
    @contextmanager
    def connection(self):
        """Context manager for database connections with durability pragmas."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Durability pragmas - WAL for concurrent reads + writer,
        # NORMAL synchronous for balance of speed and safety,
        # 64MB mmap for read performance.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA mmap_size=67108864")
        try:
            yield conn
        finally:
            conn.close()

    def verify_pragmas(self) -> dict:
        """Verify database pragmas are correctly set. Used by runtime gate."""
        with self.connection() as conn:
            result = {}
            for pragma in ["journal_mode", "synchronous", "foreign_keys", "busy_timeout"]:
                row = conn.execute(f"PRAGMA {pragma}").fetchone()
                result[pragma] = row[0] if row else None
        expected = {"journal_mode": "wal", "synchronous": 1, "foreign_keys": 1, "busy_timeout": 5000}
        result["all_ok"] = all(
            str(result.get(k, "")).lower() == str(v).lower()
            for k, v in expected.items()
        )
        result["expected"] = expected
        return result
    
    # ─────────────────────────────────────────────────────────────────────────
    # CRUD Operations
    # ─────────────────────────────────────────────────────────────────────────
    
    def store(self, memory_type: str, content: str, metadata: Optional[Dict] = None) -> str:
        """Store a memory in the ledger."""
        memory_id = f"mem_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            with self.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO ledger (id, type, content, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        memory_type,
                        content,
                        json.dumps(metadata) if metadata else None,
                        now,
                        now
                    )
                )
                
                # Log to audit trail
                conn.execute(
                    """
                    INSERT INTO audit_log (id, operation, ledger_id, performed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"audit_{uuid.uuid4().hex[:12]}", "CREATE", memory_id, now)
                )
                
                conn.commit()
            
            logger.info(f"Stored memory: {memory_id} ({memory_type})")
            return memory_id
        
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            raise
    
    def get(self, memory_id: str) -> Optional[Dict]:
        """Retrieve a memory by ID."""
        try:
            with self.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM ledger WHERE id = ? AND archived_at IS NULL",
                    (memory_id,)
                ).fetchone()
            
            if row:
                return dict(row)
            return None
        
        except Exception as e:
            logger.error(f"Failed to get memory {memory_id}: {e}")
            return None
    
    def search(self, query: str, limit: int = 10) -> List[Dict]:
        """Search memories by content (full-text search)."""
        try:
            with self.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT l.* FROM ledger l
                    WHERE l.archived_at IS NULL
                    AND (
                        l.content LIKE ? OR
                        l.metadata LIKE ?
                    )
                    ORDER BY l.created_at DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", f"%{query}%", limit)
                ).fetchall()
            
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            return []
    
    def update(self, memory_id: str, content: Optional[str] = None,
               metadata: Optional[Dict] = None) -> bool:
        """Update a memory.

        For v3 typed rows (validation_schema IS NOT NULL), this silently
        redirects to create_version() to enforce content immutability.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()

            with self.connection() as conn:
                # Get existing memory
                existing = conn.execute(
                    "SELECT * FROM ledger WHERE id = ? AND archived_at IS NULL",
                    (memory_id,)
                ).fetchone()

                if not existing:
                    logger.warning(f"Memory not found: {memory_id}")
                    return False

                # V3 typed row: redirect to create_version for immutability
                if existing["validation_schema"] is not None:
                    from core.typed_memory import VersionChainManager
                    vcm = VersionChainManager()
                    new_content = content if content is not None else existing["content"]
                    new_metadata = json.dumps(metadata) if metadata else existing["metadata"]
                    try:
                        vcm.create_version(
                            conn, memory_id, new_content, new_metadata,
                            existing["type"], existing["memory_subtype"],
                        )
                        conn.commit()
                        logger.info(f"Legacy update redirected to create_version for typed memory: {memory_id}")
                        return True
                    except Exception as exc:
                        logger.error(f"create_version failed for legacy update: {exc}")
                        return False

                # Legacy row: in-place update
                new_content = content if content is not None else existing['content']
                new_metadata = json.dumps(metadata) if metadata else existing['metadata']

                conn.execute(
                    """
                    UPDATE ledger
                    SET content = ?, metadata = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_content, new_metadata, now, memory_id)
                )

                # Log to audit trail
                conn.execute(
                    """
                    INSERT INTO audit_log (id, operation, ledger_id, performed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"audit_{uuid.uuid4().hex[:12]}", "UPDATE", memory_id, now)
                )

                conn.commit()

            logger.info(f"Updated memory: {memory_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            return False
    
    def delete(self, memory_id: str) -> bool:
        """Soft-delete a memory (archive it)."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            
            with self.connection() as conn:
                cursor = conn.execute(
                    "UPDATE ledger SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
                    (now, memory_id)
                )
                if cursor.rowcount == 0:
                    logger.warning(f"Memory not found for delete: {memory_id}")
                    return False
                
                # Log to audit trail
                conn.execute(
                    """
                    INSERT INTO audit_log (id, operation, ledger_id, performed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f"audit_{uuid.uuid4().hex[:12]}", "DELETE", memory_id, now)
                )
                
                conn.commit()
            
            logger.info(f"Archived memory: {memory_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False
    
    # ─────────────────────────────────────────────────────────────────────────
    # Query Operations
    # ─────────────────────────────────────────────────────────────────────────
    
    def list_by_type(self, memory_type: str, limit: int = 100) -> List[Dict]:
        """List all active memories of a specific type."""
        try:
            with self.connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM ledger
                    WHERE type = ? AND archived_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (memory_type, limit)
                ).fetchall()
            
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Failed to list memories of type {memory_type}: {e}")
            return []
    
    def count(self) -> int:
        """Get total count of active memories."""
        try:
            with self.connection() as conn:
                result = conn.execute(
                    "SELECT COUNT(*) as count FROM ledger WHERE archived_at IS NULL"
                ).fetchone()
            
            return result['count'] if result else 0
        
        except Exception as e:
            logger.error(f"Failed to get count: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            with self.connection() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) as count FROM ledger"
                ).fetchone()
                
                active = conn.execute(
                    "SELECT COUNT(*) as count FROM ledger WHERE archived_at IS NULL"
                ).fetchone()
                
                by_type = conn.execute(
                    "SELECT type, COUNT(*) as count FROM ledger WHERE archived_at IS NULL GROUP BY type"
                ).fetchall()
                
                by_type_dict = {row['type']: row['count'] for row in by_type}
            
            return {
                "total_memories": total['count'] if total else 0,
                "active_memories": active['count'] if active else 0,
                "by_type": by_type_dict,
                "database_path": self.db_path
            }
        
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {}

    # ─────────────────────────────────────────────────────────────────────────
    # V3 Typed Memory Operations
    # ─────────────────────────────────────────────────────────────────────────

    def store_typed(
        self,
        memory_type: str,
        subtype: str,
        content: str,
        metadata: Optional[Dict] = None,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a typed memory with validation + conflict detection.

        Returns {"memory_id", "valid", "validation_errors", "conflicts"}.
        """
        from core.typed_memory import (
            TypedMemoryValidator, ConflictDetector, utc_now_iso,
        )

        validator = TypedMemoryValidator()
        result = validator.validate(subtype, content, metadata, valid_from, valid_until)

        if not result["valid"]:
            return {
                "memory_id": None,
                "valid": False,
                "validation_errors": result["errors"],
                "conflicts": [],
            }

        memory_id = f"mem_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        recorded_at = now
        schema_version = validator.get_schema_version(subtype)
        metadata_json = json.dumps(metadata) if metadata else None

        # Ensure content is stored as JSON string
        if isinstance(content, dict):
            content_str = json.dumps(content)
        else:
            content_str = content

        with self.connection() as conn:
            conn.execute(
                """INSERT INTO ledger
                   (id, type, content, metadata, created_at, updated_at,
                    memory_subtype, valid_from, valid_until, recorded_at,
                    superseded_by, version_chain_head, redacted,
                    validation_schema, content_format)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, ?, 'json')""",
                (
                    memory_id, memory_type, content_str, metadata_json, now, now,
                    subtype, valid_from, valid_until, recorded_at,
                    memory_id,  # version_chain_head = self.id (head record)
                    schema_version,
                ),
            )

            # Audit
            conn.execute(
                "INSERT INTO audit_log (id, operation, ledger_id, performed_at) VALUES (?, ?, ?, ?)",
                (f"audit_{uuid.uuid4().hex[:12]}", "CREATE_TYPED", memory_id, now),
            )

            # Conflict detection (same transaction)
            detector = ConflictDetector()
            content_dict = json.loads(content_str)
            conflicts = detector.detect_conflicts(
                conn, memory_id, subtype, content_dict, valid_from, valid_until,
            )

            conn.commit()

        return {
            "memory_id": memory_id,
            "valid": True,
            "validation_errors": [],
            "conflicts": conflicts,
        }

    def query_with_budget(
        self,
        query: str,
        limit: int = 10,
        max_chars: int = 7000,
        type_filters: Optional[List[str]] = None,
        include_redacted: bool = False,
        ordered_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Search with DB-level character budget enforcement.

        Returns {"results", "count", "budget_used", "budget_limit", "truncated"}.
        First-row bypass: always returns at least 1 result even if it exceeds budget.
        """
        with self.connection() as conn:
            if ordered_ids:
                # Use pre-ranked IDs from hybrid search
                placeholders = ",".join("?" for _ in ordered_ids)
                base_sql = f"SELECT * FROM ledger WHERE id IN ({placeholders}) AND archived_at IS NULL"
                params: list = list(ordered_ids)
            else:
                base_sql = """SELECT * FROM ledger
                              WHERE archived_at IS NULL
                              AND (content LIKE ? OR metadata LIKE ?)"""
                params = [f"%{query}%", f"%{query}%"]

            # Exclude superseded
            base_sql += " AND superseded_by IS NULL"

            if not include_redacted:
                base_sql += " AND (redacted = 0 OR redacted IS NULL)"

            if type_filters:
                placeholders_t = ",".join("?" for _ in type_filters)
                base_sql += f" AND memory_subtype IN ({placeholders_t})"
                params.extend(type_filters)

            if ordered_ids:
                # Preserve hybrid search ordering via CASE
                order_clause = "ORDER BY CASE id "
                for i, oid in enumerate(ordered_ids):
                    order_clause += f"WHEN ? THEN {i} "
                    params.append(oid)
                order_clause += f"ELSE {len(ordered_ids)} END"
                base_sql += f" {order_clause}"
            else:
                base_sql += " ORDER BY COALESCE(recorded_at, created_at) DESC"

            base_sql += " LIMIT ?"
            params.append(limit)

            rows = conn.execute(base_sql, params).fetchall()

        # Apply character budget with first-row bypass
        results = []
        budget_used = 0
        truncated = False

        for i, row in enumerate(rows):
            row_dict = dict(row)
            content_len = len(row_dict.get("content", "") or "")
            if budget_used + content_len > max_chars and i > 0:
                truncated = True
                break
            results.append(row_dict)
            budget_used += content_len

        return {
            "results": results,
            "count": len(results),
            "budget_used": budget_used,
            "budget_limit": max_chars,
            "truncated": truncated,
        }

    def get_conflicts(
        self,
        memory_id: Optional[str] = None,
        resolved: Optional[bool] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List conflicts, optionally filtered by memory_id and resolved status."""
        with self.connection() as conn:
            sql = "SELECT * FROM memory_conflicts WHERE 1=1"
            params: list = []

            if memory_id:
                sql += " AND (memory_id_a = ? OR memory_id_b = ?)"
                params.extend([memory_id, memory_id])

            if resolved is not None:
                sql += " AND resolved = ?"
                params.append(1 if resolved else 0)

            sql += " ORDER BY detected_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def resolve_conflict(self, conflict_id: str, resolution_note: str) -> bool:
        """Mark a conflict as resolved."""
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE memory_conflicts SET resolved = 1, resolution_note = ? WHERE conflict_id = ? AND resolved = 0",
                (resolution_note, conflict_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_version_history(self, memory_id: str) -> List[Dict[str, Any]]:
        """Get version history for a memory."""
        from core.typed_memory import VersionChainManager
        vcm = VersionChainManager()
        with self.connection() as conn:
            return vcm.get_version_history(conn, memory_id)

    def create_version(
        self,
        original_id: str,
        new_content: str,
        metadata: Optional[Dict] = None,
        valid_from: Optional[str] = None,
    ) -> str:
        """Create a new version superseding original_id."""
        from core.typed_memory import VersionChainManager
        vcm = VersionChainManager()
        metadata_json = json.dumps(metadata) if metadata else None

        with self.connection() as conn:
            # Get type + subtype from original
            orig = conn.execute(
                "SELECT type, memory_subtype FROM ledger WHERE id = ?",
                (original_id,),
            ).fetchone()
            if orig is None:
                raise ValueError(f"Original memory not found: {original_id}")

            new_id = vcm.create_version(
                conn, original_id, new_content, metadata_json,
                orig["type"], orig["memory_subtype"],
                valid_from=valid_from,
            )
            conn.commit()

        return new_id

    def redact_memory(self, memory_id: str, reason: str, performed_by: str = "system") -> bool:
        """Redact a memory (governance operation)."""
        from core.typed_memory import RedactionManager
        rm = RedactionManager()
        with self.connection() as conn:
            result = rm.redact(conn, memory_id, reason, performed_by)
            conn.commit()
            return result

    def unredact_memory(self, memory_id: str, performed_by: str = "system") -> bool:
        """Unredact a memory (admin operation)."""
        from core.typed_memory import RedactionManager
        rm = RedactionManager()
        with self.connection() as conn:
            result = rm.unredact(conn, memory_id, performed_by)
            conn.commit()
            return result

    def get_redaction_audit(self, memory_id: str) -> List[Dict[str, Any]]:
        """Get redaction audit trail for a memory."""
        from core.typed_memory import RedactionManager
        rm = RedactionManager()
        with self.connection() as conn:
            return rm.get_audit_trail(conn, memory_id)


# Global database instance
_db = None


def get_db() -> MemoryDatabase:
    """Get or create global database instance."""
    global _db
    if _db is None:
        _db = MemoryDatabase()
    return _db
