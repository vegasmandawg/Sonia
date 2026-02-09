"""
Session & Stream Schemas — Stage 3
Pydantic models for session control plane, WebSocket stream events,
and tool confirmation endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


# ──────────────────────────────────────────────────────────────────────────────
# Session control plane
# ──────────────────────────────────────────────────────────────────────────────

class SessionCreateRequest(BaseModel):
    user_id: str
    conversation_id: str
    profile: str = "chat_low_latency"
    metadata: Optional[Dict[str, Any]] = None


class SessionInfo(BaseModel):
    session_id: str
    user_id: str
    conversation_id: str
    profile: str
    status: str                          # active, closed, expired
    created_at: str
    expires_at: str
    last_activity: str
    turn_count: int = 0
    active_streams: int = 0
    metadata: Optional[Dict[str, Any]] = None


class SessionCreateResponse(BaseModel):
    ok: bool = True
    session_id: str
    created_at: str
    expires_at: str
    status: str = "active"


class SessionDeleteResponse(BaseModel):
    ok: bool = True
    session_id: str
    closed_at: str


# ──────────────────────────────────────────────────────────────────────────────
# Stream event envelope
# ──────────────────────────────────────────────────────────────────────────────

class StreamEvent(BaseModel):
    """Bidirectional event envelope for WebSocket /v1/stream."""
    type: str
    session_id: str = ""
    turn_id: str = ""
    timestamp: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Tool confirmation
# ──────────────────────────────────────────────────────────────────────────────

class ConfirmationInfo(BaseModel):
    confirmation_id: str
    session_id: str
    turn_id: str
    tool_name: str
    args: Dict[str, Any]
    summary: str
    status: str                          # pending, approved, denied, expired
    created_at: str
    remaining_seconds: float


class ConfirmationDecisionRequest(BaseModel):
    reason: Optional[str] = None


class ConfirmationDecisionResponse(BaseModel):
    ok: bool
    confirmation_id: str
    status: str                          # approved, denied, expired, ...
    reason: str


# ──────────────────────────────────────────────────────────────────────────────
# Turn state (for stream mode tracking)
# ──────────────────────────────────────────────────────────────────────────────

TURN_STATES = ("IDLE", "LISTENING", "THINKING", "TOOLING", "RESPONDING", "COMPLETE")
