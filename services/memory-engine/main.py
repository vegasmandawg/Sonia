"""
Sonia Memory Engine - Main Entry Point

Persistent memory and knowledge management with SQLite backend.
Provides ledger-based storage, vector indexing, and semantic search.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import sys
import json
from datetime import datetime
from typing import Optional, Dict, List
from pydantic import BaseModel

from db import get_db, MemoryDatabase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('memory-engine')

# Initialize database
db = get_db()

# Create FastAPI app
app = FastAPI(
    title="Sonia Memory Engine",
    description="Persistent memory and knowledge management",
    version="1.0.0"
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

class UpdateRequest(BaseModel):
    content: Optional[str] = None
    metadata: Optional[Dict] = None

# ─────────────────────────────────────────────────────────────────────────────
# Health & Status Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    """Health check endpoint."""
    stats = db.get_stats()
    return {
        "ok": True,
        "service": "memory-engine",
        "timestamp": datetime.utcnow().isoformat(),
        "memories": stats.get("active_memories", 0)
    }

@app.get("/")
def root():
    """Root endpoint."""
    return {
        "service": "memory-engine",
        "status": "online",
        "version": "1.0.0",
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
            except:
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
                except:
                    pass
            
            formatted_results.append({
                "id": result['id'],
                "type": result['type'],
                "content": result['content'],
                "metadata": metadata,
                "created_at": result['created_at']
            })
        
        return {
            "query": request.query,
            "results": formatted_results,
            "count": len(formatted_results),
            "service": "memory-engine"
        }
    except Exception as e:
        logger.error(f"Search error: {e}")
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
            except:
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
def list_by_type(memory_type: str, limit: int = 100):
    """List all memories of a specific type."""
    try:
        results = db.list_by_type(memory_type, limit=limit)
        
        formatted = []
        for result in results:
            metadata = {}
            if result.get('metadata'):
                try:
                    metadata = json.loads(result['metadata'])
                except:
                    pass
            
            formatted.append({
                "id": result['id'],
                "type": result['type'],
                "content": result['content'],
                "metadata": metadata,
                "created_at": result['created_at']
            })
        
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
            "service": "memory-engine"
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

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
            "error": "internal_server_error",
            "message": str(exc),
            "service": "memory-engine"
        }
    )

# ─────────────────────────────────────────────────────────────────────────────
# Startup & Shutdown
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    logger.info("Memory Engine starting up...")
    stats = db.get_stats()
    logger.info(f"Database loaded: {stats.get('active_memories', 0)} active memories")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Memory Engine shutting down...")

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
