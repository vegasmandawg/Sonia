"""Request models for Memory Engine API."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EventAppendRequest(BaseModel):
    """Request to append event to ledger."""
    event_type: str = Field(..., description="Type of event")
    entity_id: str = Field(..., description="Entity ID (session, user, etc.)")
    payload: Dict[str, Any] = Field(..., description="Event payload")


class DocumentIngestRequest(BaseModel):
    """Request to ingest document."""
    content: str = Field(..., description="Document content")
    doc_type: str = Field(..., description="Document type")
    metadata: Optional[Dict[str, Any]] = Field(None)


class SearchRequest(BaseModel):
    """Request to search memory."""
    query: str = Field(..., description="Search query")
    limit: int = Field(10, ge=1, le=100)
    include_scores: bool = Field(True)


class SnapshotCreateRequest(BaseModel):
    """Request to create snapshot."""
    session_id: str = Field(..., description="Session ID")
