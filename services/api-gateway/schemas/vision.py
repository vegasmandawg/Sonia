"""
Stage 4 — Vision & Multimodal Schemas
Pydantic models for vision ingestion, turn quality annotations,
memory policy, and latency breakdown.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


# ──────────────────────────────────────────────────────────────────────────────
# Vision ingestion
# ──────────────────────────────────────────────────────────────────────────────

ALLOWED_MIME_TYPES = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif",
})

# Configurable limits
DEFAULT_MAX_FRAME_BYTES = 1_048_576     # 1 MiB
DEFAULT_MAX_FRAMES_PER_MINUTE = 10
DEFAULT_MAX_FRAMES_PER_TURN = 3


class VisionConfig(BaseModel):
    """Per-session vision configuration (immutable after session create)."""
    enabled: bool = False
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    max_frames_per_minute: int = DEFAULT_MAX_FRAMES_PER_MINUTE
    max_frames_per_turn: int = DEFAULT_MAX_FRAMES_PER_TURN


class VisionFrame(BaseModel):
    """Validated vision frame after ingest."""
    frame_id: str
    mime_type: str
    size_bytes: int
    # base64 data kept separately to avoid serializing it repeatedly
    data_b64: str = Field(exclude=True, default="")


# ──────────────────────────────────────────────────────────────────────────────
# Turn quality annotations
# ──────────────────────────────────────────────────────────────────────────────

class QualityAnnotations(BaseModel):
    generation_profile_used: str = "chat_low_latency"
    fallback_used: bool = False
    tool_calls_attempted: int = 0
    tool_calls_executed: int = 0
    completion_reason: str = "ok"     # ok | timeout | fallback | error


class ResponsePolicy(BaseModel):
    """Configurable guardrails for turn responses."""
    max_output_chars: int = 4000
    max_tool_calls_per_turn: int = 5
    disallow_empty_response: bool = True
    fallback_on_model_timeout: bool = True
    primary_profile: str = "chat_low_latency"
    fallback_profile: str = "chat_low_latency"


# ──────────────────────────────────────────────────────────────────────────────
# Latency breakdown
# ──────────────────────────────────────────────────────────────────────────────

class LatencyBreakdown(BaseModel):
    """Per-turn latency instrumentation (all in milliseconds)."""
    asr_ms: float = 0.0
    vision_ms: float = 0.0
    memory_read_ms: float = 0.0
    model_ms: float = 0.0
    tool_ms: float = 0.0
    memory_write_ms: float = 0.0
    total_ms: float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Memory write / retrieval policy
# ──────────────────────────────────────────────────────────────────────────────

# Memory item types for tagging
MEMORY_TYPES = frozenset({
    "turn_raw", "turn_summary", "tool_event",
    "confirmation_event", "vision_observation",
})

DEFAULT_CONTEXT_TOKEN_BUDGET = 2000     # approximate char budget for prompt
DEFAULT_RETRIEVAL_LIMIT = 8


class MemoryWritePolicy(BaseModel):
    """Controls what and how we write to memory-engine."""
    write_raw: bool = True
    write_summary: bool = True
    include_vision_observation: bool = True
    include_tool_events: bool = True
    include_confirmation_events: bool = True


class MemoryRetrievalPolicy(BaseModel):
    """Controls what and how we retrieve from memory-engine."""
    limit: int = DEFAULT_RETRIEVAL_LIMIT
    context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET
    prefer_summaries: bool = True
    type_filters: List[str] = Field(
        default_factory=lambda: ["turn_summary", "turn_raw"]
    )
