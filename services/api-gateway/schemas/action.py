"""
Stage 5 — Action Pipeline Schemas
Typed intent envelopes for the plan → validate → execute → verify lifecycle.
"""

from typing import Any, Dict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


# ── Risk levels ──────────────────────────────────────────────────────────────

RiskLevel = Literal["safe", "low", "medium", "high", "critical"]

# ── Action lifecycle states ──────────────────────────────────────────────────

ActionState = Literal[
    "planned",          # Action created, awaiting validation
    "validated",        # Passed pre-flight checks
    "pending_approval", # Guarded action waiting for operator confirmation
    "approved",         # Operator approved
    "denied",           # Operator denied
    "executing",        # Currently running
    "verifying",        # Post-execution verification in progress
    "succeeded",        # Completed successfully and verified
    "failed",           # Execution or verification failed
    "cancelled",        # Cancelled before execution
    "timeout",          # Execution timed out
    "rolled_back",      # Rollback completed after failure
]


# ── Action intent envelope ───────────────────────────────────────────────────

class ActionIntent(BaseModel):
    """
    Typed intent envelope for a desktop action.
    Immutable once created; state changes tracked in ActionRecord.
    """
    action_id: str = Field(
        default_factory=lambda: f"act_{uuid.uuid4().hex[:16]}",
        description="Deterministic action identifier"
    )
    intent: str = Field(
        ...,
        description="Action intent key (e.g. 'file.read', 'shell.run', 'app.launch')"
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Action parameters"
    )
    risk_level: RiskLevel = Field(
        default="medium",
        description="Risk classification"
    )
    requires_confirmation: bool = Field(
        default=False,
        description="Whether operator confirmation is required"
    )
    timeout_ms: int = Field(
        default=10000,
        ge=100,
        le=120000,
        description="Maximum execution time in milliseconds"
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=5,
        description="Maximum retry attempts on transient failure"
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate execution"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation ID for distributed tracing"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Associated session ID"
    )
    dry_run: bool = Field(
        default=False,
        description="If true, validate and plan but do not execute"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata for the action"
    )


# ── Validation result ────────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    """Result of pre-flight validation for an action."""
    valid: bool = Field(..., description="Whether action passed all checks")
    checks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Individual check results"
    )
    risk_level: RiskLevel = Field(
        default="medium",
        description="Assessed risk level (may differ from declared)"
    )
    requires_confirmation: bool = Field(
        default=False,
        description="Whether this action requires operator approval"
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason if validation fails"
    )


# ── Execution result ─────────────────────────────────────────────────────────

class ExecutionResult(BaseModel):
    """Result of action execution."""
    success: bool = Field(..., description="Whether execution succeeded")
    output: Dict[str, Any] = Field(
        default_factory=dict,
        description="Execution output data"
    )
    side_effects: List[str] = Field(
        default_factory=list,
        description="List of side effects produced"
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Structured error code if failed"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Human-readable error message"
    )
    retries_used: int = Field(
        default=0,
        description="Number of retries consumed"
    )
    duration_ms: float = Field(
        default=0.0,
        description="Execution duration in milliseconds"
    )


# ── Telemetry record ─────────────────────────────────────────────────────────

class ActionTelemetry(BaseModel):
    """Timing and observability data for an action lifecycle."""
    plan_ms: float = Field(default=0.0)
    validate_ms: float = Field(default=0.0)
    approval_wait_ms: float = Field(default=0.0)
    execute_ms: float = Field(default=0.0)
    verify_ms: float = Field(default=0.0)
    total_ms: float = Field(default=0.0)


# ── Full action record ───────────────────────────────────────────────────────

class ActionRecord(BaseModel):
    """
    Complete lifecycle record for a single action.
    Created at plan time, updated through validate → execute → verify.
    """
    action_id: str = Field(..., description="Action identifier")
    intent: str = Field(..., description="Action intent key")
    params: Dict[str, Any] = Field(default_factory=dict)
    state: ActionState = Field(default="planned")
    risk_level: RiskLevel = Field(default="medium")
    requires_confirmation: bool = Field(default=False)
    dry_run: bool = Field(default=False)
    idempotency_key: Optional[str] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(default=None)

    # Lifecycle results
    validation: Optional[ValidationResult] = Field(default=None)
    execution: Optional[ExecutionResult] = Field(default=None)
    telemetry: ActionTelemetry = Field(default_factory=ActionTelemetry)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)

    # Retry tracking
    max_retries: int = Field(default=0)
    retry_count: int = Field(default=0)
    timeout_ms: int = Field(default=10000)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + "Z" if not v.isoformat().endswith("Z") else v.isoformat()
        }


# ── API request/response models ──────────────────────────────────────────────

class ActionPlanRequest(BaseModel):
    """Request to plan (and optionally execute) an action."""
    intent: str = Field(..., description="Action intent key")
    params: Dict[str, Any] = Field(default_factory=dict)
    timeout_ms: int = Field(default=10000, ge=100, le=120000)
    max_retries: int = Field(default=0, ge=0, le=5)
    idempotency_key: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False, description="Plan and validate only")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionPlanResponse(BaseModel):
    """Response from action plan/execute."""
    ok: bool = Field(...)
    action_id: str = Field(...)
    state: ActionState = Field(...)
    intent: str = Field(...)
    risk_level: RiskLevel = Field(default="medium")
    requires_confirmation: bool = Field(default=False)
    validation: Optional[ValidationResult] = Field(default=None)
    execution: Optional[ExecutionResult] = Field(default=None)
    telemetry: Optional[ActionTelemetry] = Field(default=None)
    error: Optional[Dict[str, Any]] = Field(default=None)
    correlation_id: Optional[str] = Field(default=None)


class ActionStatusResponse(BaseModel):
    """Response for action status query."""
    ok: bool = Field(default=True)
    action: Optional[ActionRecord] = Field(default=None)
    error: Optional[Dict[str, Any]] = Field(default=None)


class ActionQueueResponse(BaseModel):
    """Response listing actions in the queue."""
    ok: bool = Field(default=True)
    actions: List[ActionRecord] = Field(default_factory=list)
    total: int = Field(default=0)
    filters: Dict[str, Any] = Field(default_factory=dict)
