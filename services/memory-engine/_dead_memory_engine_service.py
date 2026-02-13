"""
FastAPI Service Wrapper for Memory Engine

Exposes memory operations over HTTP with async request handling.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field

from .memory_engine import MemoryEngine
from .models.requests import (
    EventAppendRequest,
    DocumentIngestRequest,
    SearchRequest,
    SnapshotCreateRequest,
)
from .models.responses import (
    EventResponse,
    SearchResultResponse,
    SnapshotResponse,
    HealthResponse,
    StatsResponse,
)

logger = logging.getLogger(__name__)


class MemoryEngineService:
    """FastAPI service wrapper for Memory Engine."""

    def __init__(self, engine: Optional[MemoryEngine] = None):
        """Initialize service with Memory Engine instance."""
        self.engine = engine or MemoryEngine()
        self.app = FastAPI(title="Sonia Memory Engine", version="1.0.0")
        self._setup_routes()

    def _setup_routes(self) -> None:
        """Setup FastAPI routes."""

        @self.app.on_event("startup")
        async def startup():
            """Initialize Memory Engine on startup."""
            logger.info("Memory Engine service starting...")
            await self.engine.initialize()
            logger.info("Memory Engine service ready")

        @self.app.on_event("shutdown")
        async def shutdown():
            """Shutdown Memory Engine gracefully."""
            logger.info("Memory Engine service shutting down...")
            await self.engine.shutdown()
            logger.info("Memory Engine service stopped")

        # Health endpoints
        @self.app.get("/health", response_model=HealthResponse)
        async def health():
            """Health check endpoint."""
            return await self.engine.health_check()

        @self.app.get("/status", response_model=Dict[str, Any])
        async def status():
            """Status endpoint with statistics."""
            health = await self.engine.health_check()
            stats = await self.engine.get_stats()
            return {
                "service": "memory-engine",
                "version": "1.0.0",
                "health": health,
                "stats": stats,
            }

        # Ledger endpoints
        @self.app.post("/api/v1/memory/append", response_model=EventResponse)
        async def append_event(req: EventAppendRequest):
            """Append event to ledger."""
            try:
                event_id = await self.engine.append_event(
                    event_type=req.event_type,
                    entity_id=req.entity_id,
                    payload=req.payload,
                )
                return EventResponse(event_id=event_id, success=True)
            except Exception as e:
                logger.error(f"Failed to append event: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/v1/memory/query", response_model=Dict[str, Any])
        async def query_ledger(
            entity_id: Optional[str] = Query(None),
            event_type: Optional[str] = Query(None),
            start_time: Optional[str] = Query(None),
            end_time: Optional[str] = Query(None),
            limit: int = Query(100, le=1000),
        ):
            """Query ledger with optional filters."""
            try:
                results = await self.engine.query_ledger(
                    entity_id=entity_id,
                    event_type=event_type,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                )
                return {"results": results, "count": len(results)}
            except Exception as e:
                logger.error(f"Query failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # Workspace/Document endpoints
        @self.app.post("/api/v1/workspace/ingest", response_model=Dict[str, str])
        async def ingest_document(req: DocumentIngestRequest):
            """Ingest and chunk document."""
            try:
                doc_id = await self.engine.ingest_document(
                    content=req.content,
                    doc_type=req.doc_type,
                    metadata=req.metadata or {},
                )
                return {"doc_id": doc_id, "status": "ingested"}
            except Exception as e:
                logger.error(f"Document ingestion failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/api/v1/workspace/documents", response_model=Dict[str, Any])
        async def list_documents(doc_type: Optional[str] = Query(None)):
            """List all documents."""
            try:
                documents = await self.engine.list_documents(doc_type)
                return {"documents": documents, "count": len(documents)}
            except Exception as e:
                logger.error(f"Failed to list documents: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # Retrieval endpoints
        @self.app.post("/api/v1/search", response_model=Dict[str, Any])
        async def search(req: SearchRequest):
            """Hybrid search (semantic + BM25)."""
            try:
                results = await self.engine.search(
                    query=req.query,
                    limit=req.limit,
                    include_scores=req.include_scores,
                )
                return {
                    "query": req.query,
                    "results": results,
                    "count": len(results),
                }
            except Exception as e:
                logger.error(f"Search failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get(
            "/api/v1/search/entity/{entity_id}",
            response_model=Dict[str, Any],
        )
        async def search_entity(
            entity_id: str,
            limit: int = Query(50, le=1000),
        ):
            """Search memory for specific entity."""
            try:
                results = await self.engine.search_by_entity(
                    entity_id, limit
                )
                return {
                    "entity_id": entity_id,
                    "results": results,
                    "count": len(results),
                }
            except Exception as e:
                logger.error(f"Entity search failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        # Snapshot endpoints
        @self.app.post(
            "/api/v1/snapshots/create",
            response_model=SnapshotResponse,
        )
        async def create_snapshot(req: SnapshotCreateRequest):
            """Create memory snapshot."""
            try:
                snapshot_id = await self.engine.create_snapshot(
                    req.session_id
                )
                return SnapshotResponse(
                    snapshot_id=snapshot_id,
                    session_id=req.session_id,
                    success=True,
                )
            except Exception as e:
                logger.error(f"Snapshot creation failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/api/v1/snapshots/restore/{snapshot_id}")
        async def restore_snapshot(snapshot_id: str):
            """Restore from snapshot."""
            try:
                result = await self.engine.restore_snapshot(snapshot_id)
                return {
                    "snapshot_id": snapshot_id,
                    "restored": result,
                }
            except Exception as e:
                logger.error(f"Snapshot restore failed: {e}")
                raise HTTPException(status_code=500, detail=str(e))
