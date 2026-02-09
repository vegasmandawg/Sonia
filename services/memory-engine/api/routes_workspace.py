"""Document workspace endpoints."""

from fastapi import APIRouter
from typing import Optional

router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])


@router.post("/ingest")
async def ingest_document(content: str, doc_type: str, metadata: Optional[dict] = None):
    """Ingest and chunk document."""
    return {"doc_id": "...", "status": "ingested"}


@router.get("/documents")
async def list_documents(doc_type: Optional[str] = None):
    """List all documents."""
    return {"documents": [], "count": 0}
