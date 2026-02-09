"""
Perception Pipeline -- v2.6 Track B (production-hardened)

Event-driven inference: only runs VLM on triggers (wake word + intent,
motion event, user command). Structured SceneAnalysis output with
confirmation required on ALL actions (enforced at service layer).

Privacy check: refuses inference when vision-capture privacy is disabled.
Even if events arrive, no inference runs with privacy off.

Event bus contract:
  - vision.frame.available  (input: new frame in buffer)
  - perception.requested    (input: explicit analysis request)
  - perception.completed    (output: SceneAnalysis result)

Port: 7070 | Health: /healthz
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator

logger = logging.getLogger("perception")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VISION_CAPTURE_URL = "http://127.0.0.1:7060"
MODEL_ROUTER_URL = "http://127.0.0.1:7010"
MAX_GPU_BUDGET_MS = 2000
INFERENCE_TIMEOUT_S = 10.0


class TriggerType(str, Enum):
    WAKE_WORD = "wake_word"
    MOTION = "motion"
    USER_COMMAND = "user_command"
    SCHEDULED = "scheduled"


class PerceptionStatus(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Event bus contract
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    FRAME_AVAILABLE = "vision.frame.available"
    PERCEPTION_REQUESTED = "perception.requested"
    PERCEPTION_COMPLETED = "perception.completed"


class EventEnvelope(BaseModel):
    """Unified event envelope for cross-service communication."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    source: str = ""
    type: EventType
    correlation_id: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# SceneAnalysis (strict validation)
# ---------------------------------------------------------------------------

class Entity(BaseModel):
    label: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: Optional[Dict[str, float]] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SceneAnalysis(BaseModel):
    scene_id: str = Field(min_length=1)
    timestamp: float = Field(gt=0)
    trigger: TriggerType
    summary: str = Field(min_length=1)
    entities: List[Entity] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: Optional[str] = None
    # ENFORCED AT SERVICE LAYER: always True, cannot be overridden
    action_requires_confirmation: bool = True
    inference_ms: float = Field(ge=0.0)
    model_used: Optional[str] = None
    correlation_id: str = ""
    privacy_verified: bool = False

    @validator("action_requires_confirmation", always=True)
    def force_confirmation(cls, v):
        """Service-layer enforcement: confirmation is ALWAYS required."""
        return True


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class PerceptionRequest(BaseModel):
    trigger: TriggerType
    context: str = ""
    frame_count: int = Field(default=1, ge=1, le=5)
    max_inference_ms: float = MAX_GPU_BUDGET_MS
    correlation_id: str = ""


# ---------------------------------------------------------------------------
# Service state
# ---------------------------------------------------------------------------

class PerceptionState:
    def __init__(self):
        self.status: PerceptionStatus = PerceptionStatus.IDLE
        self.total_inferences: int = 0
        self.total_errors: int = 0
        self.total_privacy_blocks: int = 0
        self.avg_inference_ms: float = 0.0
        self.last_scene: Optional[SceneAnalysis] = None
        self._inference_times: list = []
        self.events_emitted: int = 0
        self.started_at: float = time.time()

    def record_inference(self, ms: float) -> None:
        self._inference_times.append(ms)
        if len(self._inference_times) > 100:
            self._inference_times = self._inference_times[-100:]
        self.avg_inference_ms = sum(self._inference_times) / len(self._inference_times)
        self.total_inferences += 1


state = PerceptionState()


# ---------------------------------------------------------------------------
# Privacy check
# ---------------------------------------------------------------------------

async def check_vision_privacy() -> Dict[str, Any]:
    """Check vision-capture privacy status. Returns privacy info dict."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{VISION_CAPTURE_URL}/v1/vision/privacy/status")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning(f"Could not check vision privacy: {e}")
        # Fail closed: treat as privacy disabled
        return {"privacy": "disabled", "capture_allowed": False}


async def fetch_frames(n: int = 1) -> list:
    """Fetch latest frames from vision-capture service."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{VISION_CAPTURE_URL}/v1/vision/frames/latest",
                params={"n": n},
            )
            resp.raise_for_status()
            return resp.json().get("frames", [])
    except Exception as e:
        logger.warning(f"Failed to fetch frames: {e}")
        return []


# ---------------------------------------------------------------------------
# VLM inference
# ---------------------------------------------------------------------------

async def run_vlm_inference(
    frames: list,
    context: str,
    max_ms: float,
) -> dict:
    """
    Send frames + context to model-router for VLM inference.
    Returns structured scene analysis data.

    Currently a stub -- real implementation will call model-router
    with task_type=vision_analysis.
    """
    start = time.perf_counter()
    # Stub: simulate minimal latency
    await asyncio.sleep(0.05)
    elapsed_ms = (time.perf_counter() - start) * 1000

    frame_desc = f"{len(frames)} frame(s)"
    ctx_desc = f"context: '{context[:50]}'" if context else "no context"

    return {
        "summary": f"Scene analysis ({frame_desc}, {ctx_desc})",
        "entities": [],
        "overall_confidence": 0.0,
        "recommended_action": None,
        "inference_ms": round(elapsed_ms, 1),
        "model_used": "stub/none",
    }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Perception pipeline starting")
    yield
    logger.info("Perception pipeline stopped")


app = FastAPI(title="Perception Pipeline", version="2.6.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes: health
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "service": "perception",
        "version": "2.6.0",
        "inference_status": state.status.value,
        "total_inferences": state.total_inferences,
        "privacy_blocks": state.total_privacy_blocks,
    }


# ---------------------------------------------------------------------------
# Routes: status
# ---------------------------------------------------------------------------

@app.get("/v1/perception/status")
async def get_status():
    return {
        "status": state.status.value,
        "total_inferences": state.total_inferences,
        "total_errors": state.total_errors,
        "total_privacy_blocks": state.total_privacy_blocks,
        "avg_inference_ms": round(state.avg_inference_ms, 1),
        "last_scene_id": state.last_scene.scene_id if state.last_scene else None,
        "events_emitted": state.events_emitted,
        "uptime_seconds": round(time.time() - state.started_at, 1),
    }


# ---------------------------------------------------------------------------
# Routes: analyze (main inference path)
# ---------------------------------------------------------------------------

@app.post("/v1/perception/analyze", response_model=SceneAnalysis)
async def analyze(req: PerceptionRequest):
    """
    Trigger scene analysis. Checks privacy FIRST, then fetches frames,
    runs VLM inference, returns structured SceneAnalysis.

    action_requires_confirmation is ALWAYS True (enforced by Pydantic validator).
    """
    if state.status == PerceptionStatus.PROCESSING:
        raise HTTPException(429, "BUSY: inference already in progress")

    # Privacy check FIRST -- no inference when disabled
    privacy = await check_vision_privacy()
    if privacy.get("privacy") == "disabled" or not privacy.get("capture_allowed", False):
        state.total_privacy_blocks += 1
        raise HTTPException(
            403,
            "PRIVACY_BLOCKED: vision privacy is disabled, no inference permitted"
        )

    state.status = PerceptionStatus.PROCESSING
    correlation_id = req.correlation_id or str(uuid.uuid4())

    try:
        frames = await fetch_frames(req.frame_count)
        if not frames:
            state.status = PerceptionStatus.IDLE
            raise HTTPException(
                503,
                "NO_FRAMES: no frames available from vision-capture"
            )

        result = await run_vlm_inference(frames, req.context, req.max_inference_ms)

        scene = SceneAnalysis(
            scene_id=str(uuid.uuid4()),
            timestamp=time.time(),
            trigger=req.trigger,
            summary=result["summary"],
            entities=[Entity(**e) for e in result.get("entities", [])],
            overall_confidence=result.get("overall_confidence", 0.0),
            recommended_action=result.get("recommended_action"),
            action_requires_confirmation=True,  # redundant but explicit
            inference_ms=result.get("inference_ms", 0.0),
            model_used=result.get("model_used"),
            correlation_id=correlation_id,
            privacy_verified=True,
        )

        state.record_inference(scene.inference_ms)
        state.last_scene = scene
        state.status = PerceptionStatus.IDLE
        state.events_emitted += 1
        return scene

    except HTTPException:
        state.status = PerceptionStatus.IDLE
        raise
    except Exception as e:
        state.total_errors += 1
        state.status = PerceptionStatus.ERROR
        logger.error(f"Perception error: {e}", exc_info=True)
        raise HTTPException(500, f"INFERENCE_ERROR: {e}")


# ---------------------------------------------------------------------------
# Routes: last scene
# ---------------------------------------------------------------------------

@app.get("/v1/perception/last")
async def get_last_scene():
    if state.last_scene is None:
        raise HTTPException(404, "No scene analysis available yet")
    return state.last_scene


# ---------------------------------------------------------------------------
# Routes: event ingestion (for event bus integration)
# ---------------------------------------------------------------------------

@app.post("/v1/perception/events")
async def receive_event(event: EventEnvelope):
    """
    Receive events from the event bus. Currently handles:
    - vision.frame.available: triggers analysis if not busy
    - perception.requested: explicit analysis request
    """
    if event.type == EventType.FRAME_AVAILABLE:
        # Only process if idle and privacy allows
        if state.status != PerceptionStatus.IDLE:
            return {"accepted": False, "reason": "busy"}
        # Delegate to analyze
        req = PerceptionRequest(
            trigger=TriggerType.MOTION,
            context=event.payload.get("context", ""),
            frame_count=1,
            correlation_id=event.correlation_id,
        )
        try:
            scene = await analyze(req)
            return {"accepted": True, "scene_id": scene.scene_id}
        except HTTPException as e:
            return {"accepted": False, "reason": e.detail}

    elif event.type == EventType.PERCEPTION_REQUESTED:
        req = PerceptionRequest(
            trigger=TriggerType(event.payload.get("trigger", "user_command")),
            context=event.payload.get("context", ""),
            frame_count=event.payload.get("frame_count", 1),
            correlation_id=event.correlation_id,
        )
        try:
            scene = await analyze(req)
            return {"accepted": True, "scene_id": scene.scene_id}
        except HTTPException as e:
            return {"accepted": False, "reason": e.detail}

    return {"accepted": False, "reason": f"unknown event type: {event.type}"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=7070, log_level="info")
