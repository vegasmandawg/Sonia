"""Memory ledger endpoints."""

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])


@router.post("/append")
async def append_event(event_type: str, entity_id: str, payload: dict):
    """Append event to ledger."""
    return {"event_id": "...", "success": True}


@router.get("/query")
async def query_ledger(
    entity_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    limit: int = Query(100),
):
    """Query ledger with optional filters."""
    return {"results": [], "count": 0}
