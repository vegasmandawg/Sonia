"""
OpenClaw Request/Response Schemas
Pydantic models for request/response validation with deterministic structure.
"""

from typing import Any, Dict, List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


# ============================================================================
# Request Schemas
# ============================================================================

class ExecuteRequest(BaseModel):
    """Execute a tool with arguments."""
    
    tool_name: str = Field(..., description="Tool identifier (e.g., 'shell.run')")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout_ms: Optional[int] = Field(default=5000, description="Execution timeout in milliseconds")
    correlation_id: Optional[str] = Field(default=None, description="Request correlation ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "tool_name": "shell.run",
                "args": {"command": "Get-ChildItem"},
                "timeout_ms": 5000,
                "correlation_id": "req_001"
            }
        }


# ============================================================================
# Response Schemas
# ============================================================================

class ExecuteResponse(BaseModel):
    """Unified execution response envelope."""
    
    status: Literal["executed", "not_implemented", "policy_denied", "timeout", "error"] = Field(
        ..., description="Execution status"
    )
    tool_name: str = Field(..., description="Tool that was executed")
    result: Dict[str, Any] = Field(default_factory=dict, description="Execution result")
    side_effects: List[str] = Field(default_factory=list, description="Side effects of execution")
    message: Optional[str] = Field(default=None, description="Status message")
    error: Optional[str] = Field(default=None, description="Error details if failed")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    correlation_id: Optional[str] = Field(default=None, description="Request correlation ID")
    duration_ms: float = Field(default=0.0, description="Execution duration in milliseconds")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + 'Z' if v.isoformat()[-1] != 'Z' else v.isoformat()
        }


class NotImplementedResponse(ExecuteResponse):
    """Response when tool is not yet implemented."""
    
    status: Literal["not_implemented"] = "not_implemented"
    message: str = "Tool not yet implemented"


class PolicyDeniedResponse(ExecuteResponse):
    """Response when policy prevents execution."""
    
    status: Literal["policy_denied"] = "policy_denied"
    message: str = "Policy denied execution"


class TimeoutResponse(ExecuteResponse):
    """Response when execution times out."""
    
    status: Literal["timeout"] = "timeout"
    message: str = "Execution timeout"


class ErrorResponse(ExecuteResponse):
    """Response when execution fails with error."""
    
    status: Literal["error"] = "error"
    message: str = "Execution failed"


# ============================================================================
# Tool Registry Models
# ============================================================================

class ToolMetadata(BaseModel):
    """Metadata for a registered tool."""
    
    name: str = Field(..., description="Tool name (e.g., 'shell.run')")
    display_name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="Tool description")
    tier: Literal["TIER_0_READONLY", "TIER_1_COMPUTE", "TIER_2_CREATE", "TIER_3_DESTRUCTIVE"] = Field(
        ..., description="Security tier"
    )
    requires_sandboxing: bool = Field(default=True, description="Whether sandbox is required")
    default_timeout_ms: int = Field(default=5000, description="Default timeout in milliseconds")
    allowed_by_default: bool = Field(default=True, description="Whether allowed by default")


class RegistryStats(BaseModel):
    """Statistics about the tool registry."""
    
    total_tools: int = Field(0, description="Total registered tools")
    implemented_tools: int = Field(0, description="Implemented tools")
    readonly_tools: int = Field(0, description="Read-only tools")
    compute_tools: int = Field(0, description="Compute tools")
    create_tools: int = Field(0, description="Create tools")
    destructive_tools: int = Field(0, description="Destructive tools")


# ============================================================================
# Health Check Models
# ============================================================================

class HealthzResponse(BaseModel):
    """Universal health check response."""
    
    ok: bool = Field(True, description="Service health status")
    service: str = Field("openclaw", description="Service name")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    tools_registered: int = Field(0, description="Number of registered tools")
    tools_implemented: int = Field(0, description="Number of implemented tools")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + 'Z' if v.isoformat()[-1] != 'Z' else v.isoformat()
        }


class StatusResponse(BaseModel):
    """Status response with detailed information."""
    
    service: str = Field("openclaw", description="Service name")
    status: str = Field("online", description="Service status")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    version: str = Field("1.0.0", description="Service version")
    tools: RegistryStats = Field(default_factory=RegistryStats, description="Tool statistics")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + 'Z' if v.isoformat()[-1] != 'Z' else v.isoformat()
        }
