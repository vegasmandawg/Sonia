"""Retrieval/search endpoints."""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("")
async def search(query: str, limit: int = Query(10)):
    """Hybrid search (semantic + BM25)."""
    return {"query": query, "results": [], "count": 0}


@router.get("/entity/{entity_id}")
async def search_entity(entity_id: str, limit: int = Query(50)):
    """Search memory for specific entity."""
    return {"entity_id": entity_id, "results": [], "count": 0}
