"""Deprecated workspace router placeholder.

Workspace endpoints are now served directly by services/memory-engine/main.py.
This module remains only to avoid import errors from stale references.
"""

from fastapi import APIRouter, HTTPException
from typing import Optional

router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])


@router.post("/ingest")
async def ingest_document(content: str, doc_type: str, metadata: Optional[dict] = None):
    """Deprecated endpoint."""
    raise HTTPException(
        status_code=410,
        detail="Deprecated router module. Use /v1/workspace/ingest on main.py service.",
    )


@router.get("/documents")
async def list_documents(doc_type: Optional[str] = None):
    """Deprecated endpoint."""
    raise HTTPException(
        status_code=410,
        detail="Deprecated router module. Use /v1/workspace/documents on main.py service.",
    )
