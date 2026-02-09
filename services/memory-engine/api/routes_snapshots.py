"""Snapshot management endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"])


@router.post("/create")
async def create_snapshot(session_id: str):
    """Create memory snapshot."""
    return {"snapshot_id": "...", "session_id": session_id, "success": True}


@router.post("/restore/{snapshot_id}")
async def restore_snapshot(snapshot_id: str):
    """Restore from snapshot."""
    return {"snapshot_id": snapshot_id, "restored": {}}
