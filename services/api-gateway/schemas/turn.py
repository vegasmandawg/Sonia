"""
Turn Pipeline Schemas
Pydantic models for the /v1/turn end-to-end orchestration endpoint.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid


# ──────────────────────────────────────────────────────────────────────────────
# Request
# ──────────────────────────────────────────────────────────────────────────────

class TurnRequest(BaseModel):
    user_id: str
    conversation_id: str
    input_text: str
    profile: str = "chat_low_latency"
    metadata: Optional[Dict[str, Any]] = None


# ──────────────────────────────────────────────────────────────────────────────
# Response sub-objects
# ──────────────────────────────────────────────────────────────────────────────

class ToolCallRecord(BaseModel):
    tool_name: str
    args: Dict[str, Any]
    status: str                     # "executed", "not_implemented", "policy_denied", etc.
    result: Optional[Dict[str, Any]] = None

class MemorySummary(BaseModel):
    written: bool
    retrieved_count: int

class TurnResponse(BaseModel):
    ok: bool
    turn_id: str
    assistant_text: str = ""
    tool_calls: Optional[List[ToolCallRecord]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    memory: MemorySummary
    duration_ms: float = 0.0
    error: Optional[Dict[str, Any]] = None


# ──────────────────────────────────────────────────────────────────────────────
# Internal turn record (for memory persistence)
# ──────────────────────────────────────────────────────────────────────────────

class TurnRecord(BaseModel):
    turn_id: str
    user_id: str
    conversation_id: str
    input_text: str
    assistant_text: str
    tool_calls: Optional[List[ToolCallRecord]] = None
    started_at: str
    finished_at: str
