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
import hashlib
import secrets

# Canonical version
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION, SONIA_CONTRACT
try:
    from log_redaction import redact_string
except ImportError:
    redact_string = lambda x: x

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


# ── Identity / Session / History Models ───────────────────────────────────

class CreateUserRequest(BaseModel):
    display_name: str

class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    metadata: Optional[Dict] = None

class PersistSessionRequest(BaseModel):
    session_id: str
    user_id: str
    conversation_id: str
    profile: str = "chat_low_latency"
    status: str = "active"
    created_at: str
    expires_at: str
    last_activity: str
    turn_count: int = 0
    metadata: Optional[Dict] = None

class UpdateSessionRequest(BaseModel):
    status: Optional[str] = None
    turn_count: Optional[int] = None
    last_activity: Optional[str] = None
    expires_at: Optional[str] = None
    metadata: Optional[Dict] = None

class WriteTurnRequest(BaseModel):
    turn_id: str
    session_id: str
    user_id: str
    sequence_num: int
    user_input: str
    assistant_response: Optional[str] = None
    model_used: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    latency_ms: Optional[float] = None
    metadata: Optional[Dict] = None


# ── V3 Memory Models ─────────────────────────────────────────────────────

class StoreTypedRequest(BaseModel):
    type: str
    subtype: str  # FACT | PREFERENCE | PROJECT | SESSION_CONTEXT | SYSTEM_STATE
    content: str  # JSON string
    metadata: Optional[Dict] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None

class QueryBudgetRequest(BaseModel):
    query: str
    limit: int = 10
    max_chars: int = 7000
    type_filters: Optional[List[str]] = None
    include_redacted: bool = False

class VersionCreateRequest(BaseModel):
    original_id: str
    new_content: str
    metadata: Optional[Dict] = None
    valid_from: Optional[str] = None

class RedactRequest(BaseModel):
    memory_id: str
    reason: str
    performed_by: str = "system"

class ConflictResolveRequest(BaseModel):
    resolution_note: str

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
        "contract_version": SONIA_CONTRACT,
        "timestamp": datetime.utcnow().isoformat(),
        "memories": stats.get("active_memories", 0),
        "hybrid_search": hybrid_stats,
    }


@app.get("/version")
def version():
    """Version endpoint."""
    return {
        "ok": True,
        "service": "memory-engine",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
        "python_version": sys.version.split()[0],
    }


@app.get("/pragmas")
def pragmas():
    """Runtime pragma verification gate. Fails fast if durability pragmas not set."""
    result = db.verify_pragmas()
    if not result["all_ok"]:
        raise HTTPException(status_code=500, detail={"error": "PRAGMA_VIOLATION", "pragmas": result})
    return {"ok": True, "service": "memory-engine", "pragmas": result}


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

class TrackProvenanceRequest(BaseModel):
    memory_id: str
    source_type: str = "direct"
    source_id: Optional[str] = None
    metadata: Optional[Dict] = None


@app.post("/v1/provenance/track")
def track_provenance(request: TrackProvenanceRequest):
    """Track provenance for a memory item (M4: perception bridge uses this)."""
    try:
        _provenance.track(
            memory_id=request.memory_id,
            source_type=request.source_type,
            source_id=request.source_id,
            metadata=request.metadata,
        )
        return {
            "status": "tracked",
            "memory_id": request.memory_id,
            "source_type": request.source_type,
            "service": "memory-engine",
        }
    except Exception as e:
        logger.error(f"Provenance track error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


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
# Identity Endpoints (M2)
# ─────────────────────────────────────────────────────────────────────────────

def _hash_key(api_key: str) -> str:
    """SHA-256 hash of an API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _generate_api_key() -> str:
    """Generate a 32-byte hex API key prefixed with 'sk-sonia-'."""
    return f"sk-sonia-{secrets.token_hex(32)}"


@app.post("/v1/users")
def create_user(request: CreateUserRequest):
    """Create a new user and return their API key (shown only once)."""
    user_id = f"usr_{uuid4().hex[:16]}"
    api_key = _generate_api_key()
    key_hash = _hash_key(api_key)
    now = datetime.utcnow().isoformat()

    with db.connection() as conn:
        conn.execute(
            """INSERT INTO users (user_id, display_name, api_key_hash, created_at, updated_at, status, metadata)
               VALUES (?, ?, ?, ?, ?, 'active', '{}')""",
            (user_id, request.display_name, key_hash, now, now),
        )
        conn.commit()

    return {
        "user_id": user_id,
        "display_name": request.display_name,
        "api_key": api_key,
        "created_at": now,
        "service": "memory-engine",
        "_warning": "Store this API key securely. It will not be shown again.",
    }


@app.get("/v1/users/by-key")
def get_user_by_key(api_key_hash: str):
    """Internal: look up user by API key hash. Used by auth middleware."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT user_id, display_name, status FROM users WHERE api_key_hash = ? AND status = 'active'",
            (api_key_hash,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No active user for key")
    return {
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "status": row["status"],
        "service": "memory-engine",
    }


@app.get("/v1/users/{user_id}")
def get_user(user_id: str):
    """Get user profile (no API key returned)."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT user_id, display_name, created_at, updated_at, status, metadata FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")

    metadata = {}
    if row["metadata"]:
        try:
            metadata = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": metadata,
        "service": "memory-engine",
    }


@app.get("/v1/users")
def list_users(status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List users with optional status filter."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with db.connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT user_id, display_name, status, created_at FROM users WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT user_id, display_name, status, created_at FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
    return {
        "users": [dict(r) for r in rows],
        "count": len(rows),
        "service": "memory-engine",
    }


@app.put("/v1/users/{user_id}")
def update_user(user_id: str, request: UpdateUserRequest):
    """Update user display_name or metadata."""
    now = datetime.utcnow().isoformat()
    with db.connection() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"User not found: {user_id}")

        if request.display_name is not None:
            conn.execute("UPDATE users SET display_name = ?, updated_at = ? WHERE user_id = ?",
                         (request.display_name, now, user_id))
        if request.metadata is not None:
            conn.execute("UPDATE users SET metadata = ?, updated_at = ? WHERE user_id = ?",
                         (json.dumps(request.metadata), now, user_id))
        conn.commit()

    return {"status": "updated", "user_id": user_id, "service": "memory-engine"}


@app.delete("/v1/users/{user_id}")
def delete_user(user_id: str):
    """Soft-delete a user (set status=deleted)."""
    now = datetime.utcnow().isoformat()
    with db.connection() as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
        conn.execute("UPDATE users SET status = 'deleted', updated_at = ? WHERE user_id = ?", (now, user_id))
        conn.commit()
    return {"status": "deleted", "user_id": user_id, "service": "memory-engine"}


@app.post("/v1/users/{user_id}/rotate-key")
def rotate_key(user_id: str):
    """Generate a new API key, invalidating the old one."""
    now = datetime.utcnow().isoformat()
    with db.connection() as conn:
        row = conn.execute("SELECT user_id, status FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
        if row["status"] != "active":
            raise HTTPException(status_code=400, detail="Cannot rotate key for non-active user")

        new_key = _generate_api_key()
        new_hash = _hash_key(new_key)
        conn.execute("UPDATE users SET api_key_hash = ?, updated_at = ? WHERE user_id = ?",
                     (new_hash, now, user_id))
        conn.commit()

    return {
        "user_id": user_id,
        "api_key": new_key,
        "rotated_at": now,
        "service": "memory-engine",
        "_warning": "Store this API key securely. It will not be shown again.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Session Persistence Endpoints (M2)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/v1/sessions/persist")
def persist_session(request: PersistSessionRequest):
    """Write or update a session record to durable storage."""
    metadata_json = json.dumps(request.metadata) if request.metadata else "{}"
    with db.connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, user_id, conversation_id, profile, status, created_at, expires_at, last_activity, turn_count, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (request.session_id, request.user_id, request.conversation_id,
             request.profile, request.status, request.created_at,
             request.expires_at, request.last_activity, request.turn_count, metadata_json),
        )
        conn.commit()

    return {"status": "persisted", "session_id": request.session_id, "service": "memory-engine"}


@app.get("/v1/sessions/load/{session_id}")
def load_session(session_id: str):
    """Load a persisted session by ID."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    metadata = {}
    if row["metadata"]:
        try:
            metadata = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "conversation_id": row["conversation_id"],
        "profile": row["profile"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "last_activity": row["last_activity"],
        "turn_count": row["turn_count"],
        "metadata": metadata,
        "service": "memory-engine",
    }


@app.get("/v1/users/{user_id}/sessions")
def list_user_sessions(user_id: str, status: Optional[str] = None, limit: int = 50, offset: int = 0):
    """List sessions for a user with optional status filter."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with db.connection() as conn:
        if status:
            rows = conn.execute(
                """SELECT session_id, conversation_id, profile, status, created_at, last_activity, turn_count
                   FROM sessions WHERE user_id = ? AND status = ? ORDER BY last_activity DESC LIMIT ? OFFSET ?""",
                (user_id, status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT session_id, conversation_id, profile, status, created_at, last_activity, turn_count
                   FROM sessions WHERE user_id = ? ORDER BY last_activity DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset),
            ).fetchall()

    return {
        "user_id": user_id,
        "sessions": [dict(r) for r in rows],
        "count": len(rows),
        "service": "memory-engine",
    }


@app.put("/v1/sessions/update/{session_id}")
def update_session(session_id: str, request: UpdateSessionRequest):
    """Update fields on a persisted session."""
    with db.connection() as conn:
        row = conn.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

        if request.status is not None:
            conn.execute("UPDATE sessions SET status = ? WHERE session_id = ?", (request.status, session_id))
        if request.turn_count is not None:
            conn.execute("UPDATE sessions SET turn_count = ? WHERE session_id = ?", (request.turn_count, session_id))
        if request.last_activity is not None:
            conn.execute("UPDATE sessions SET last_activity = ? WHERE session_id = ?", (request.last_activity, session_id))
        if request.expires_at is not None:
            conn.execute("UPDATE sessions SET expires_at = ? WHERE session_id = ?", (request.expires_at, session_id))
        if request.metadata is not None:
            conn.execute("UPDATE sessions SET metadata = ? WHERE session_id = ?", (json.dumps(request.metadata), session_id))
        conn.commit()

    return {"status": "updated", "session_id": session_id, "service": "memory-engine"}


@app.get("/v1/sessions/active")
def list_active_sessions(limit: int = 200):
    """List all active sessions (for gateway restore on startup)."""
    limit = max(1, min(limit, 500))
    with db.connection() as conn:
        rows = conn.execute(
            """SELECT session_id, user_id, conversation_id, profile, status,
                      created_at, expires_at, last_activity, turn_count, metadata
               FROM sessions WHERE status = 'active' ORDER BY last_activity DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    sessions = []
    for row in rows:
        meta = {}
        if row["metadata"]:
            try:
                meta = json.loads(row["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        entry = dict(row)
        entry["metadata"] = meta
        sessions.append(entry)

    return {"sessions": sessions, "count": len(sessions), "service": "memory-engine"}


# ─────────────────────────────────────────────────────────────────────────────
# Conversation History Endpoints (M2)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/v1/history/turns")
def write_turn(request: WriteTurnRequest):
    """Write a conversation turn to durable storage."""
    now = datetime.utcnow().isoformat()
    tool_calls_json = json.dumps(request.tool_calls) if request.tool_calls else None
    metadata_json = json.dumps(request.metadata) if request.metadata else None

    with db.connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO conversation_turns
               (turn_id, session_id, user_id, sequence_num, user_input, assistant_response,
                model_used, tool_calls, latency_ms, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (request.turn_id, request.session_id, request.user_id,
             request.sequence_num, request.user_input, request.assistant_response,
             request.model_used, tool_calls_json, request.latency_ms,
             metadata_json, now),
        )
        conn.commit()

    return {"status": "stored", "turn_id": request.turn_id, "service": "memory-engine"}


@app.get("/v1/sessions/{session_id}/history")
def get_session_history(session_id: str, limit: int = 100, offset: int = 0):
    """Get conversation turns for a session, ordered by sequence_num."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    with db.connection() as conn:
        rows = conn.execute(
            """SELECT turn_id, session_id, user_id, sequence_num, user_input, assistant_response,
                      model_used, tool_calls, latency_ms, metadata, created_at
               FROM conversation_turns WHERE session_id = ?
               ORDER BY sequence_num ASC LIMIT ? OFFSET ?""",
            (session_id, limit, offset),
        ).fetchall()

    turns = []
    for row in rows:
        entry = dict(row)
        if entry.get("tool_calls"):
            try:
                entry["tool_calls"] = json.loads(entry["tool_calls"])
            except (json.JSONDecodeError, TypeError):
                pass
        if entry.get("metadata"):
            try:
                entry["metadata"] = json.loads(entry["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        turns.append(entry)

    return {
        "session_id": session_id,
        "turns": turns,
        "count": len(turns),
        "service": "memory-engine",
    }


@app.get("/v1/users/{user_id}/history")
def get_user_history(user_id: str, limit: int = 50, offset: int = 0):
    """Get recent conversation turns across all sessions for a user."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    with db.connection() as conn:
        rows = conn.execute(
            """SELECT turn_id, session_id, user_id, sequence_num, user_input, assistant_response,
                      model_used, latency_ms, created_at
               FROM conversation_turns WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()

    return {
        "user_id": user_id,
        "turns": [dict(r) for r in rows],
        "count": len(rows),
        "service": "memory-engine",
    }


# ─────────────────────────────────────────────────────────────────────────────
# V3 Memory Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/v3/memory/store")
def v3_store(request: StoreTypedRequest):
    """Store a typed memory with validation + conflict detection."""
    try:
        result = db.store_typed(
            memory_type=request.type,
            subtype=request.subtype,
            content=request.content,
            metadata=request.metadata,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
        )

        if not result["valid"]:
            raise HTTPException(status_code=400, detail={
                "code": "VALIDATION_FAILED",
                "errors": result["validation_errors"],
            })

        return {
            "status": "stored",
            "id": result["memory_id"],
            "type": request.type,
            "subtype": request.subtype,
            "conflicts": result["conflicts"],
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"V3 store error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v3/memory/query")
def v3_query(request: QueryBudgetRequest):
    """Search with DB-level budget enforcement."""
    try:
        result = db.query_with_budget(
            query=request.query,
            limit=request.limit,
            max_chars=request.max_chars,
            type_filters=request.type_filters,
            include_redacted=request.include_redacted,
        )

        formatted_results = []
        for r in result["results"]:
            # Mask redacted content
            entry = {
                "id": r["id"],
                "type": r["type"],
                "memory_subtype": r.get("memory_subtype"),
                "created_at": r["created_at"],
                "recorded_at": r.get("recorded_at"),
                "version_chain_head": r.get("version_chain_head"),
            }
            if r.get("redacted"):
                entry["content"] = "[REDACTED]"
                entry["metadata"] = None
            else:
                entry["content"] = r["content"]
                metadata = {}
                if r.get("metadata"):
                    try:
                        metadata = json.loads(r["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                entry["metadata"] = metadata
            formatted_results.append(entry)

        return {
            "query": request.query,
            "results": formatted_results,
            "count": result["count"],
            "budget_used": result["budget_used"],
            "budget_limit": result["budget_limit"],
            "truncated": result["truncated"],
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except Exception as e:
        logger.error(f"V3 query error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v3/memory/{memory_id}/versions")
def v3_version_history(memory_id: str):
    """Get version history for a memory."""
    try:
        history = db.get_version_history(memory_id)
        if not history:
            raise HTTPException(status_code=404, detail=f"No version history for: {memory_id}")

        formatted = []
        for r in history:
            entry = {
                "id": r["id"],
                "type": r["type"],
                "memory_subtype": r.get("memory_subtype"),
                "recorded_at": r.get("recorded_at"),
                "superseded_by": r.get("superseded_by"),
                "version_chain_head": r.get("version_chain_head"),
                "redacted": r.get("redacted", 0),
            }
            if r.get("redacted"):
                entry["content"] = "[REDACTED]"
            else:
                entry["content"] = r["content"]
            formatted.append(entry)

        return {
            "memory_id": memory_id,
            "versions": formatted,
            "count": len(formatted),
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"V3 version history error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v3/memory/version")
def v3_create_version(request: VersionCreateRequest):
    """Create a new version superseding an existing memory."""
    try:
        new_id = db.create_version(
            original_id=request.original_id,
            new_content=request.new_content,
            metadata=request.metadata,
            valid_from=request.valid_from,
        )
        return {
            "status": "version_created",
            "id": new_id,
            "original_id": request.original_id,
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except Exception as e:
        error_str = str(e)
        if "already superseded" in error_str:
            raise HTTPException(status_code=409, detail={
                "code": "CONCURRENT_SUPERSEDE",
                "message": error_str,
            })
        logger.error(f"V3 create version error: {e}")
        raise HTTPException(status_code=400, detail=error_str)


@app.post("/v3/memory/redact")
def v3_redact(request: RedactRequest):
    """Redact a memory (governance operation)."""
    try:
        success = db.redact_memory(
            memory_id=request.memory_id,
            reason=request.reason,
            performed_by=request.performed_by,
        )
        if not success:
            raise HTTPException(status_code=404, detail=f"Memory not found or already redacted: {request.memory_id}")
        return {
            "status": "redacted",
            "memory_id": request.memory_id,
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"V3 redact error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v3/memory/{memory_id}/redaction-audit")
def v3_redaction_audit(memory_id: str):
    """Get redaction audit trail."""
    try:
        audit = db.get_redaction_audit(memory_id)
        return {
            "memory_id": memory_id,
            "audit_trail": audit,
            "count": len(audit),
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except Exception as e:
        logger.error(f"V3 redaction audit error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v3/memory/conflicts")
def v3_list_conflicts(
    memory_id: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
):
    """List conflicts with optional filters."""
    try:
        conflicts = db.get_conflicts(memory_id=memory_id, resolved=resolved, limit=limit)
        # Parse metadata JSON
        for c in conflicts:
            if c.get("metadata"):
                try:
                    c["metadata"] = json.loads(c["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass
        return {
            "conflicts": conflicts,
            "count": len(conflicts),
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except Exception as e:
        logger.error(f"V3 list conflicts error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v3/memory/conflicts/{conflict_id}/resolve")
def v3_resolve_conflict(conflict_id: str, request: ConflictResolveRequest):
    """Resolve a conflict."""
    try:
        success = db.resolve_conflict(conflict_id, request.resolution_note)
        if not success:
            raise HTTPException(status_code=404, detail=f"Conflict not found or already resolved: {conflict_id}")
        return {
            "status": "resolved",
            "conflict_id": conflict_id,
            "service": "memory-engine",
            "contract": SONIA_CONTRACT,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"V3 resolve conflict error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Error Handlers
# ─────────────────────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    redacted_error = redact_string(str(exc))
    logger.error(f"Unhandled exception: {redacted_error}")
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
