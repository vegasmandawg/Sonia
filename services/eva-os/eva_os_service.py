"""
EVA-OS FastAPI Service

Runs EVA-OS as a module integrated with the API Gateway.
This can eventually become its own service (port TBD) or stay embedded in the gateway.

Current model: EVA-OS logic runs here; gateway calls it via HTTP or direct import.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
import json
import logging
from eva_os import EVAOSOrchestrator, SoniaMode, ServiceHealth, ServiceName

# Setup logging to S:\logs\services\eva-os.out.log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("S:\\logs\\services\\eva-os.out.log", mode="a"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("eva-os-service")

app = FastAPI(
    title="EVA-OS",
    description="Sonia's Supervisory Control Plane",
    version="1.0.0"
)

# Global EVA-OS instance
eva: Optional[EVAOSOrchestrator] = None


# ============================================================================
# Request/Response Models
# ============================================================================

class HealthCheckResponse(BaseModel):
    status: str = "ok"
    eva_os_ready: bool
    message: str = "EVA-OS operational"


class UserTurnRequest(BaseModel):
    id: str
    text: str
    mode: str = "conversation"
    language: str = "en-US"
    confidence: float = 1.0
    input_type: str = "text"
    metadata: Optional[Dict] = None


class ToolCallRequest(BaseModel):
    id: str
    tool_name: str
    args: Dict[str, Any]
    side_effects_declared: Optional[List[str]] = None
    expected_outputs: Optional[List[str]] = None
    timeout_ms: Optional[int] = None


class ApprovalResponseRequest(BaseModel):
    approval_request_id: str
    decision: str  # "approved" or "denied"
    approval_token: str
    reason: Optional[str] = None


class ServiceHealthUpdateRequest(BaseModel):
    source_service: str
    health_status: str
    details: Optional[Dict] = None


# ============================================================================
# Lifecycle Endpoints
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize EVA-OS on startup."""
    global eva
    logger.info("Starting EVA-OS service...")
    
    try:
        # Initialize EVA-OS with root contract
        eva = EVAOSOrchestrator(root_contract="S:\\")
        
        # Initialize service health (all healthy for now; will be updated by gateway)
        eva.initialize_stack_health({
            "GATEWAY": "HEALTHY",
            "PIPECAT": "HEALTHY",
            "MEMORY_ENGINE": "HEALTHY",
            "MODEL_ROUTER": "HEALTHY",
            "OPENCLAW": "HEALTHY",
        })
        
        logger.info("EVA-OS initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize EVA-OS: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("EVA-OS service shutting down")


# ============================================================================
# Health and Status Endpoints
# ============================================================================

@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint."""
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    return HealthCheckResponse(
        status="ok",
        eva_os_ready=True,
        message="EVA-OS operational"
    )


@app.get("/status")
async def get_status():
    """Get current EVA-OS operational state."""
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    return eva.get_current_state()


# ============================================================================
# Orchestration Endpoints
# ============================================================================

@app.post("/process-turn")
async def process_user_turn(request: UserTurnRequest):
    """
    Process an incoming user turn.
    
    This is the main entry point for user input.
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        result = eva.process_user_turn(request.dict())
        return {
            "status": "success",
            "result": result,
        }
    except Exception as e:
        logger.error(f"Error processing turn: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/gate-tool-call")
async def gate_tool_call(request: ToolCallRequest):
    """
    Validate and gate a tool call before execution.
    
    Returns either:
    - "approved" if tool can execute
    - "approval_required" with an ApprovalRequest if user must approve
    - "blocked" if tool call violates policy
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        result = eva.validate_and_gate_tool_call(request.dict())
        return {
            "status": "success",
            "result": result,
        }
    except Exception as e:
        logger.error(f"Error gating tool call: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process-approval")
async def process_approval(request: ApprovalResponseRequest):
    """
    Process user's approval or denial of a tool call.
    
    The user must provide:
    - approval_request_id: from the ApprovalRequest
    - decision: "approved" or "denied"
    - approval_token: token from the ApprovalRequest (validates scope)
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        result = eva.process_approval_response(request.dict())
        return {
            "status": "success",
            "result": result,
        }
    except Exception as e:
        logger.error(f"Error processing approval: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/process-tool-result")
async def process_tool_result(result: Dict[str, Any]):
    """
    Process result from OpenClaw tool execution.
    
    EVA-OS uses this to update task state and verify outcomes.
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        outcome = eva.process_tool_result(result)
        return {
            "status": "success",
            "result": outcome,
        }
    except Exception as e:
        logger.error(f"Error processing tool result: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/service-health-update")
async def update_service_health(request: ServiceHealthUpdateRequest):
    """
    Update service health status.
    
    Called by the gateway or services themselves to report health.
    EVA-OS uses this to update capabilities and degrade gracefully.
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        result = eva.handle_service_health_change(request.dict())
        return {
            "status": "success",
            "result": result,
        }
    except Exception as e:
        logger.error(f"Error updating service health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Mode and Policy Endpoints
# ============================================================================

@app.post("/set-mode/{mode}")
async def set_mode(mode: str):
    """
    Change operational mode.
    
    Valid modes: conversation, operator, diagnostic, dictation, build
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        mode_enum = SoniaMode[mode.upper()]
        eva.state.set_mode(mode_enum)
        return {
            "status": "success",
            "new_mode": mode,
            "state": eva.get_current_state(),
        }
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")
    except Exception as e:
        logger.error(f"Error setting mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Debug/Diagnostic Endpoints
# ============================================================================

@app.get("/debug/state")
async def debug_state():
    """Get full EVA-OS state (debug only)."""
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    return eva.get_current_state()


@app.post("/debug/initialize-health")
async def debug_initialize_health(health_map: Dict[str, str]):
    """
    (DEBUG) Manually initialize service health.
    
    Useful for testing and simulation.
    """
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not initialized")
    
    try:
        eva.initialize_stack_health(health_map)
        return {
            "status": "success",
            "message": "Service health initialized",
            "state": eva.get_current_state(),
        }
    except Exception as e:
        logger.error(f"Error initializing health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Liveliness and Ready Endpoints (for container orchestration)
# ============================================================================

@app.get("/ready")
async def ready():
    """Readiness probe: returns 200 if EVA-OS can accept requests."""
    if eva is None:
        raise HTTPException(status_code=503, detail="EVA-OS not ready")
    return {"ready": True}


@app.get("/alive")
async def alive():
    """Liveness probe: returns 200 if service is still running."""
    return {"alive": True}


# ============================================================================
# Root endpoint
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "eva-os",
        "version": "1.0.0",
        "description": "Sonia's Supervisory Control Plane",
        "docs_url": "/docs",
    }


# ============================================================================
# Run service (if executed directly)
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting EVA-OS FastAPI service on 127.0.0.1:7050")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=7050,
        log_level="info",
    )
