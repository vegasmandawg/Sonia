"""
Memory Engine Database Module

SQLite-backed persistence for the Sonia memory system.
Provides CRUD operations with audit logging and schema versioning.
"""

import sqlite3
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

logger = logging.getLogger('memory-engine.db')

# Default database path
DB_PATH = Path(__file__).parent.parent.parent / "data" / "memory.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


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
            with open(SCHEMA_PATH, 'r') as f:
                schema = f.read()
            
            with self.connection() as conn:
                conn.executescript(schema)
                conn.commit()
            
            logger.info("Database schema initialized")
        else:
            logger.warning(f"Schema file not found: {SCHEMA_PATH}")
    
    @contextmanager
    def connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
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
        """Update a memory."""
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
                
                # Update with provided values
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
                conn.execute(
                    "UPDATE ledger SET archived_at = ? WHERE id = ? AND archived_at IS NULL",
                    (now, memory_id)
                )
                
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


# Global database instance
_db = None


def get_db() -> MemoryDatabase:
    """Get or create global database instance."""
    global _db
    if _db is None:
        _db = MemoryDatabase()
    return _db
