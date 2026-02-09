"""Response models for Memory Engine API."""

from typing import Any, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class EventResponse(BaseModel):
    """Response for event append."""
    event_id: str
    success: bool
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class SearchResultResponse(BaseModel):
    """Single search result."""
    chunk_id: str
    content: str
    score: float
    relevance: float
    provenance: Dict[str, Any]


class SnapshotResponse(BaseModel):
    """Response for snapshot operations."""
    snapshot_id: str
    session_id: str
    success: bool
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    ledger: Dict[str, Any]
    workspace: Dict[str, Any]
    vector: Dict[str, Any]
    db: Dict[str, Any]
    timestamp: str


class StatsResponse(BaseModel):
    """Statistics response."""
    ledger_items: int
    documents: int
    vector_embeddings: int
    snapshots: int
    memory_usage_mb: float
    vector_index_size_mb: float
    timestamp: str
