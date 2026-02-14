"""
Sonia Memory Engine - Main Entry Point

Persistent memory and knowledge management with SQLite backend.
Provides ledger-based storage, vector indexing, and semantic search.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import sys
import json
from datetime import datetime
from typing import Optional, Dict, List
from pydantic import BaseModel
from uuid import uuid4

# Canonical version
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION

from db import get_db, MemoryDatabase
from hybrid_search import HybridSearchLayer
from core.provenance import ProvenanceTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('memory-engine')

# Initialize database
db = get_db()

# Initialize hybrid search layer
_hybrid = HybridSearchLayer(db)

# Initialize provenance tracker
_provenance = ProvenanceTracker(db)

# Create FastAPI app
app = FastAPI(
    title="Sonia Memory Engine",
    description="Persistent memory and knowledge management",
    version=SONIA_VERSION
)

# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────

class StoreRequest(BaseModel):
    type: str  # fact, preference, project, belief
    content: str
    metadata: Optional[Dict] = None

class RecallRequest(BaseModel):
    query: str
    limit: int = 10
    max_tokens: Optional[int] = None

class HybridSearchRequest(BaseModel):
    query: str
    limit: int = 10
    max_tokens: Optional[int] = None  # token budget for retrieval

class UpdateRequest(BaseModel):
    content: Optional[str] = None
    metadata: Optional[Dict] = None


class WorkspaceIngestRequest(BaseModel):
    content: str
    doc_type: str
    metadata: Optional[Dict] = None
    chunk_size: int = 800
    overlap: int = 100


class SnapshotCreateRequest(BaseModel):
    session_id: Optional[str] = None
    metadata: Optional[Dict] = None

# ─────────────────────────────────────────────────────────────────────────────
# Health & Status Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Health check endpoint."""
    stats = db.get_stats()
    hybrid_stats = _hybrid.get_stats()
    return {
        "ok": True,
        "service": "memory-engine",
        "timestamp": datetime.utcnow().isoformat(),
        "memories": stats.get("active_memories", 0),
        "hybrid_search": hybrid_stats,
    }


@app.get("/health")
def health():
    """Compatibility health alias for legacy tooling."""
    return healthz()

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "memory-engine",
        "status": "online",
        "version": SONIA_VERSION,
        "database": "SQLite"
    }

@app.get("/status")
def status():
    """Detailed status endpoint."""
    stats = db.get_stats()
    return {
        "service": "memory-engine",
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "ledger": {
            "total": stats.get("total_memories", 0),
            "active": stats.get("active_memories", 0),
            "by_type": stats.get("by_type", {})
        },
        "database": {
            "type": "SQLite",
            "path": stats.get("database_path", "")
        }
    }

# ─────────────────────────────────────────────────────────────────────────────
# Memory CRUD Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/store")
async def store(request: StoreRequest):
    """Store a memory in the ledger."""
    try:
        memory_id = db.store(
            memory_type=request.type,
            content=request.content,
            metadata=request.metadata
        )

        # Index in hybrid search layer (non-blocking, best-effort)
        try:
            _hybrid.on_store(memory_id, request.content)
        except Exception as e:
            logger.warning(f"Hybrid index failed for {memory_id}: {e}")

        # Track provenance (best-effort)
        try:
            source_type = (request.metadata or {}).get("source_type", "direct")
            source_id = (request.metadata or {}).get("source_id")
            _provenance.track(memory_id, source_type=source_type, source_id=source_id)
        except Exception as e:
            logger.warning(f"Provenance tracking failed for {memory_id}: {e}")

        return {
            "status": "stored",
            "id": memory_id,
            "type": request.type,
            "service": "memory-engine"
        }
    except Exception as e:
        logger.error(f"Store error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/recall/{memory_id}")
def recall(memory_id: str):
    """Recall a specific memory by ID."""
    try:
        memory = db.get(memory_id)
        
        if not memory:
            raise HTTPException(status_code=404, detail=f"Memory not found: {memory_id}")
        
        # Convert metadata back to dict
        metadata = {}
        if memory.get('metadata'):
            try:
                metadata = json.loads(memory['metadata'])
            except (json.JSONDecodeError, TypeError):
                pass
        
        return {
            "id": memory['id'],
            "type": memory['type'],
            "content": memory['content'],
            "metadata": metadata,
            "created_at": memory['created_at'],
            "updated_at": memory['updated_at'],
            "service": "memory-engine"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Recall error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/search")
async def search(request: RecallRequest):
    """Search memories by content."""
    try:
        results = db.search(request.query, limit=request.limit)

        formatted_results = []
        for result in results:
            metadata = {}
            if result.get('metadata'):
                try:
                    metadata = json.loads(result['metadata'])
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            formatted_results.append({
                "id": result['id'],
                "type": result['type'],
                "content": result['content'],
                "metadata": metadata,
                "created_at": result['created_at']
            })

        formatted_results = _apply_token_budget(formatted_results, request.max_tokens)

        return {
            "query": request.query,
            "results": formatted_results,
            "count": len(formatted_results),
            "max_tokens": request.max_tokens,
            "budget_applied": request.max_tokens is not None,
            "service": "memory-engine"
        }
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


def _apply_token_budget(results: List[Dict], max_tokens: Optional[int]) -> List[Dict]:
    """Apply token budget enforcement to search results.

    Uses a conservative 3.5 chars/token estimate (English average).
    Ensures at least one result is always returned even if it exceeds budget.
    """
    if not max_tokens or not results:
        return results
    budget_chars = int(max_tokens * 3.5)
    trimmed = []
    used = 0
    for r in results:
        content_len = len(r.get("content", ""))
        if used + content_len > budget_chars and trimmed:
            break
        trimmed.append(r)
        used += content_len
    return trimmed

@app.post("/v1/search")
async def hybrid_search(request: HybridSearchRequest):
    """Hybrid search: BM25 ranking + LIKE fallback.

    Upgraded search path for v2.9. Returns ranked results with
    score and source provenance (bm25, like_fallback).
    """
    try:
        results = _hybrid.search(request.query, limit=request.limit)

        # Token budget enforcement
        results = _apply_token_budget(results, request.max_tokens)

        return {
            "query": request.query,
            "results": results,
            "count": len(results),
            "search_mode": "hybrid",
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Hybrid search error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.put("/recall/{memory_id}")
async def update(memory_id: str, request: UpdateRequest):
    """Update a memory."""
    try:
        success = db.update(
            memory_id,
            content=request.content,
            metadata=request.metadata
        )
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Memory not found: {memory_id}")
        
        memory = db.get(memory_id)
        
        metadata = {}
        if memory.get('metadata'):
            try:
                metadata = json.loads(memory['metadata'])
            except (json.JSONDecodeError, TypeError):
                pass
        
        return {
            "status": "updated",
            "id": memory['id'],
            "type": memory['type'],
            "content": memory['content'],
            "metadata": metadata,
            "service": "memory-engine"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/recall/{memory_id}")
def delete(memory_id: str):
    """Delete (archive) a memory."""
    try:
        success = db.delete(memory_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Memory not found: {memory_id}")
        
        return {
            "status": "deleted",
            "id": memory_id,
            "service": "memory-engine"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Query Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/query/by-type/{memory_type}")
def list_by_type(memory_type: str, limit: int = 100, max_tokens: Optional[int] = None):
    """List all memories of a specific type with optional token budget."""
    limit = max(1, min(limit, 1000))
    try:
        results = db.list_by_type(memory_type, limit=limit)

        formatted = []
        for result in results:
            metadata = {}
            if result.get('metadata'):
                try:
                    metadata = json.loads(result['metadata'])
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            formatted.append({
                "id": result['id'],
                "type": result['type'],
                "content": result['content'],
                "metadata": metadata,
                "created_at": result['created_at']
            })

        # Apply token budget if requested
        formatted = _apply_token_budget(formatted, max_tokens)

        return {
            "type": memory_type,
            "results": formatted,
            "count": len(formatted),
            "service": "memory-engine"
        }
    except Exception as e:
        logger.error(f"List by type error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/query/stats")
def stats():
    """Get memory statistics."""
    try:
        stats = db.get_stats()
        return {
            **stats,
            "hybrid_search": _hybrid.get_stats(),
            "service": "memory-engine"
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Workspace & Snapshot Endpoints (canonical active surface)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/v1/workspace/ingest")
@app.post("/api/v1/workspace/ingest")
async def workspace_ingest(request: WorkspaceIngestRequest):
    """Ingest document content and persist chunks."""
    try:
        from core.chunker import Chunker

        doc_id = f"doc_{uuid4().hex[:12]}"
        chunk_size = max(200, min(request.chunk_size, 4000))
        overlap = max(0, min(request.overlap, chunk_size // 2))
        metadata = request.metadata or {}

        chunker = Chunker(chunk_size=chunk_size, overlap=overlap)
        chunks = chunker.chunk_text(request.content or "")

        with db.connection() as conn:
            conn.execute(
                """
                INSERT INTO workspace_documents
                (doc_id, doc_type, content, metadata, ingested_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    request.doc_type,
                    request.content,
                    json.dumps(metadata),
                    datetime.utcnow().isoformat(),
                ),
            )

            for i, (chunk_text, start, end) in enumerate(chunks):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO workspace_chunks
                    (chunk_id, doc_id, chunk_index, content, start_offset, end_offset)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{doc_id}_chunk_{i}",
                        doc_id,
                        i,
                        chunk_text,
                        start,
                        end,
                    ),
                )
            conn.commit()

        return {
            "status": "ingested",
            "doc_id": doc_id,
            "doc_type": request.doc_type,
            "chunk_count": len(chunks),
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Workspace ingest error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/workspace/documents")
@app.get("/api/v1/workspace/documents")
def workspace_documents(doc_type: Optional[str] = None, limit: int = 100):
    """List workspace documents with optional type filter."""
    limit = max(1, min(limit, 1000))
    try:
        with db.connection() as conn:
            if doc_type:
                rows = conn.execute(
                    """
                    SELECT doc_id, doc_type, content, metadata, ingested_at
                    FROM workspace_documents
                    WHERE doc_type = ?
                    ORDER BY ingested_at DESC
                    LIMIT ?
                    """,
                    (doc_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT doc_id, doc_type, content, metadata, ingested_at
                    FROM workspace_documents
                    ORDER BY ingested_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        documents = []
        for row in rows:
            parsed_metadata = {}
            if row["metadata"]:
                try:
                    parsed_metadata = json.loads(row["metadata"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_metadata = {}
            documents.append(
                {
                    "doc_id": row["doc_id"],
                    "doc_type": row["doc_type"],
                    "content_preview": row["content"][:200],
                    "metadata": parsed_metadata,
                    "ingested_at": row["ingested_at"],
                }
            )

        return {
            "documents": documents,
            "count": len(documents),
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Workspace list error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/workspace/chunks/{doc_id}")
def workspace_chunks(doc_id: str, limit: int = 200):
    """List persisted chunks for a workspace document."""
    limit = max(1, min(limit, 2000))
    try:
        with db.connection() as conn:
            try:
                rows = conn.execute(
                    """
                    SELECT chunk_id, chunk_index, content, start_offset, end_offset, created_at
                    FROM workspace_chunks
                    WHERE doc_id = ?
                    ORDER BY chunk_index ASC
                    LIMIT ?
                    """,
                    (doc_id, limit),
                ).fetchall()
            except Exception:
                # Backward compatibility for legacy table layouts without created_at.
                rows = conn.execute(
                    """
                    SELECT chunk_id, chunk_index, content, start_offset, end_offset
                    FROM workspace_chunks
                    WHERE doc_id = ?
                    ORDER BY chunk_index ASC
                    LIMIT ?
                    """,
                    (doc_id, limit),
                ).fetchall()

        chunks = [
            {
                "chunk_id": row["chunk_id"],
                "chunk_index": row["chunk_index"],
                "content": row["content"],
                "start_offset": row["start_offset"],
                "end_offset": row["end_offset"],
                "created_at": row["created_at"] if "created_at" in row.keys() else None,
            }
            for row in rows
        ]

        return {
            "doc_id": doc_id,
            "chunks": chunks,
            "count": len(chunks),
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Workspace chunk list error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/snapshots/create")
@app.post("/api/v1/snapshots/create")
def create_snapshot(request: SnapshotCreateRequest):
    """Create metadata snapshot of current memory state."""
    try:
        snapshot_id = f"snap_{uuid4().hex[:12]}"
        now = datetime.utcnow().isoformat()
        snapshot_metadata = request.metadata or {}
        if request.session_id:
            snapshot_metadata["session_id"] = request.session_id

        with db.connection() as conn:
            ledger_count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM ledger WHERE archived_at IS NULL"
            ).fetchone()
            ledger_count = ledger_count_row["cnt"] if ledger_count_row else 0

            document_count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM workspace_documents"
            ).fetchone()
            document_count = document_count_row["cnt"] if document_count_row else 0
            snapshot_metadata["document_count"] = document_count

            conn.execute(
                """
                INSERT INTO snapshots (id, timestamp, ledger_count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    now,
                    ledger_count,
                    json.dumps(snapshot_metadata),
                    now,
                ),
            )
            conn.commit()

        return {
            "snapshot_id": snapshot_id,
            "ledger_count": ledger_count,
            "metadata": snapshot_metadata,
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Snapshot create error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/snapshots")
def list_snapshots(limit: int = 100):
    """List latest snapshots."""
    limit = max(1, min(limit, 1000))
    try:
        with db.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, ledger_count, metadata, created_at
                FROM snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        snapshots = []
        for row in rows:
            parsed_metadata = {}
            if row["metadata"]:
                try:
                    parsed_metadata = json.loads(row["metadata"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_metadata = {}
            snapshots.append(
                {
                    "snapshot_id": row["id"],
                    "timestamp": row["timestamp"],
                    "ledger_count": row["ledger_count"],
                    "metadata": parsed_metadata,
                    "created_at": row["created_at"],
                }
            )

        return {
            "snapshots": snapshots,
            "count": len(snapshots),
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Snapshot list error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/snapshots/restore/{snapshot_id}")
@app.post("/api/v1/snapshots/restore/{snapshot_id}")
def restore_snapshot(snapshot_id: str):
    """Load snapshot metadata for restore workflows."""
    try:
        with db.connection() as conn:
            row = conn.execute(
                """
                SELECT id, timestamp, ledger_count, metadata, created_at
                FROM snapshots
                WHERE id = ?
                """,
                (snapshot_id,),
            ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Snapshot not found: {snapshot_id}")

        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}

        return {
            "snapshot_id": row["id"],
            "restored": {
                "timestamp": row["timestamp"],
                "ledger_count": row["ledger_count"],
                "metadata": metadata,
                "created_at": row["created_at"],
            },
            "service": "memory-engine",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Snapshot restore error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ─────────────────────────────────────────────────────────────────────────────
# Provenance Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/v1/provenance/{memory_id}")
def get_provenance(memory_id: str):
    """Get provenance record for a memory item."""
    record = _provenance.get_provenance(memory_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No provenance for: {memory_id}")
    return {
        "provenance": record,
        "service": "memory-engine",
    }

@app.get("/v1/provenance/{memory_id}/chain")
def get_provenance_chain(memory_id: str, max_depth: int = 10):
    """Get the full provenance chain for a memory item."""
    chain = _provenance.get_chain(memory_id, max_depth=max_depth)
    return {
        "memory_id": memory_id,
        "chain": chain,
        "depth": len(chain),
        "service": "memory-engine",
    }

# ─────────────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "service": "memory-engine",
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc)
            }
        }
    )

# ─────────────────────────────────────────────────────────────────────────────
# Startup & Shutdown
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(a):
    """Startup and shutdown lifecycle for Memory Engine."""
    logger.info("Memory Engine starting up...")
    stats = db.get_stats()
    logger.info(f"Database loaded: {stats.get('active_memories', 0)} active memories")

    try:
        _hybrid.initialize()
        h_stats = _hybrid.get_stats()
        logger.info(f"Hybrid search ready: {h_stats.get('bm25_indexed', 0)} docs indexed")
    except Exception as e:
        logger.error(f"Hybrid search init failed (LIKE fallback active): {e}")

    yield  # ── app is running ──

    logger.info("Memory Engine shutting down...")


app.router.lifespan_context = _lifespan

# ─────────────────────────────────────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Memory Engine on http://127.0.0.1:7020")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=7020,
        reload=False,
        log_level="info"
    )
