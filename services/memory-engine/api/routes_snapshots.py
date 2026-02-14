"""Deprecated snapshot router placeholder.

Snapshot endpoints are now served directly by services/memory-engine/main.py.
This module remains only to avoid import errors from stale references.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/snapshots", tags=["snapshots"])


@router.post("/create")
async def create_snapshot(session_id: str):
    """Deprecated endpoint."""
    raise HTTPException(
        status_code=410,
        detail="Deprecated router module. Use /v1/snapshots/create on main.py service.",
    )


@router.post("/restore/{snapshot_id}")
async def restore_snapshot(snapshot_id: str):
    """Deprecated endpoint."""
    raise HTTPException(
        status_code=410,
        detail="Deprecated router module. Use /v1/snapshots/restore/{snapshot_id} on main.py service.",
    )
