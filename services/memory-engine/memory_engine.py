"""
Core Memory Engine Orchestrator

Coordinates ledger, workspace, retrieval, snapshots, and vector operations.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .core.ledger_store import LedgerStore
from .core.workspace_store import WorkspaceStore
from .core.retriever import Retriever
from .core.snapshot_manager import SnapshotManager
from .core.provenance import ProvenanceTracker
from .vector.hnsw_index import HNSWIndex

try:
    from .db.sqlite import SqliteDB  # type: ignore[attr-defined]
except ImportError:
    SqliteDB = None

logger = logging.getLogger(__name__)


class MemoryEngine:
    """Main orchestrator for memory operations."""

    def __init__(
        self,
        db_path: str = "S:\\data\\memory\\ledger.db",
        vector_path: str = "S:\\data\\vector\\sonia.hnsw",
        snapshot_dir: str = "S:\\data\\memory\\snapshots",
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize Memory Engine with all subcomponents."""
        if SqliteDB is None:
            raise RuntimeError(
                "services/memory-engine/memory_engine.py is a legacy module and "
                "requires db.sqlite, which is not present. "
                "Use services/memory-engine/main.py as the active runtime surface."
            )
        self.config = config or {}
        self.db = SqliteDB(db_path)
        self.ledger = LedgerStore(self.db)
        self.workspace = WorkspaceStore(self.db)
        self.vector = HNSWIndex(vector_path)
        self.retriever = Retriever(self.ledger, self.workspace, self.vector)
        self.snapshots = SnapshotManager(snapshot_dir, self.db)
        self.provenance = ProvenanceTracker(self.db)
        self._running = False

    async def initialize(self) -> None:
        """Initialize all subcomponents."""
        logger.info("Initializing Memory Engine...")
        await self.db.initialize()
        await self.ledger.initialize()
        await self.workspace.initialize()
        await self.vector.initialize()
        await self.snapshots.initialize()
        self._running = True
        logger.info("Memory Engine initialized successfully")

    async def shutdown(self) -> None:
        """Gracefully shutdown all subcomponents."""
        logger.info("Shutting down Memory Engine...")
        self._running = False
        await self.snapshots.shutdown()
        await self.vector.shutdown()
        await self.db.shutdown()
        logger.info("Memory Engine shutdown complete")

    # Ledger operations
    async def append_event(
        self, event_type: str, entity_id: str, payload: Dict[str, Any]
    ) -> str:
        """Append event to ledger. Returns event_id."""
        if not self._running:
            raise RuntimeError("Memory Engine not running")
        
        event_id = str(uuid4())
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "entity_id": entity_id,
            "timestamp": timestamp,
            "correlation_id": payload.get("correlation_id"),
            "payload": payload,
        }
        
        await self.ledger.append(event)
        logger.info(f"Event appended: {event_id} ({event_type})")
        return event_id

    async def query_ledger(
        self,
        entity_id: Optional[str] = None,
        event_type: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query ledger with optional filtering."""
        if not self._running:
            raise RuntimeError("Memory Engine not running")
        
        return await self.ledger.query(
            entity_id=entity_id,
            event_type=event_type,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    # Workspace operations (document storage + ingestion)
    async def ingest_document(
        self, content: str, doc_type: str, metadata: Dict[str, Any]
    ) -> str:
        """Ingest document, chunk, embed. Returns doc_id."""
        if not self._running:
            raise RuntimeError("Memory Engine not running")
        
        doc_id = await self.workspace.ingest(content, doc_type, metadata)
        logger.info(f"Document ingested: {doc_id} ({doc_type})")
        return doc_id

    async def list_documents(self, doc_type: Optional[str] = None) -> List[Dict]:
        """List all documents or filter by type."""
        return await self.workspace.list_documents(doc_type)

    # Retrieval operations
    async def search(
        self,
        query: str,
        limit: int = 10,
        include_scores: bool = True,
    ) -> List[Dict[str, Any]]:
        """Hybrid search (semantic + BM25). Returns ranked results."""
        if not self._running:
            raise RuntimeError("Memory Engine not running")
        
        results = await self.retriever.search(
            query=query,
            limit=limit,
            include_scores=include_scores,
        )
        
        # Attach provenance metadata
        for result in results:
            prov = await self.provenance.get_provenance(
                result.get("chunk_id")
            )
            result["provenance"] = prov
        
        return results

    async def search_by_entity(
        self, entity_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search all memory related to specific entity."""
        return await self.retriever.search_by_entity(entity_id, limit)

    # Snapshot operations
    async def create_snapshot(self, session_id: str) -> str:
        """Create snapshot of memory state. Returns snapshot_id."""
        if not self._running:
            raise RuntimeError("Memory Engine not running")
        
        snapshot_id = await self.snapshots.create(session_id)
        logger.info(f"Snapshot created: {snapshot_id}")
        return snapshot_id

    async def restore_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """Restore memory from snapshot."""
        return await self.snapshots.restore(snapshot_id)

    # Health and status
    async def health_check(self) -> Dict[str, Any]:
        """Return health status of all subcomponents."""
        return {
            "status": "healthy" if self._running else "unhealthy",
            "ledger": await self.ledger.health(),
            "workspace": await self.workspace.health(),
            "vector": await self.vector.health(),
            "db": await self.db.health(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Return statistics about memory usage."""
        return {
            "ledger_items": await self.ledger.count(),
            "documents": await self.workspace.count(),
            "vector_embeddings": await self.vector.count(),
            "snapshots": await self.snapshots.count(),
            "memory_usage_mb": await self.db.size_mb(),
            "vector_index_size_mb": await self.vector.size_mb(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
