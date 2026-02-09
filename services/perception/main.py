"""
Perception Pipeline — v2.6 Track B

Event-driven inference: only runs VLM on triggers (wake word + intent,
motion event, user command). Produces structured output with scene summary,
entities, confidence, and recommended next action.

Runs as a FastAPI service on port 7070.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("perception")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VISION_CAPTURE_URL = "http://127.0.0.1:7060"
MODEL_ROUTER_URL = "http://127.0.0.1:7010"
MAX_GPU_BUDGET_MS = 2000  # max time per inference
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
# Schemas
# ---------------------------------------------------------------------------

class Entity(BaseModel):
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    bounding_box: Optional[Dict[str, float]] = None  # x, y, w, h (normalized 0-1)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SceneAnalysis(BaseModel):
    scene_id: str
    timestamp: float
    trigger: TriggerType
    summary: str
    entities: List[Entity] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    recommended_action: Optional[str] = None
    action_requires_confirmation: bool = True  # NEVER auto-execute
    inference_ms: float = 0.0
    model_used: Optional[str] = None


class PerceptionRequest(BaseModel):
    trigger: TriggerType
    context: str = ""  # optional text context (user's question, etc.)
    frame_count: int = Field(default=1, ge=1, le=5)
    max_inference_ms: float = MAX_GPU_BUDGET_MS


class PerceptionState:
    def __init__(self):
        self.status: PerceptionStatus = PerceptionStatus.IDLE
        self.total_inferences: int = 0
        self.total_errors: int = 0
        self.avg_inference_ms: float = 0.0
        self.last_scene: Optional[SceneAnalysis] = None
        self._inference_times: list[float] = []

    def record_inference(self, ms: float) -> None:
        self._inference_times.append(ms)
        # Keep last 100 for rolling average
        if len(self._inference_times) > 100:
            self._inference_times = self._inference_times[-100:]
        self.avg_inference_ms = sum(self._inference_times) / len(self._inference_times)
        self.total_inferences += 1


state = PerceptionState()

# ---------------------------------------------------------------------------
# VLM inference stub
# ---------------------------------------------------------------------------

async def fetch_frames(n: int = 1) -> list[dict]:
    """Fetch latest frames from vision-capture service."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{VISION_CAPTURE_URL}/v1/vision/frames/latest", params={"n": n})
            resp.raise_for_status()
            return resp.json().get("frames", [])
    except Exception as e:
        logger.warning(f"Failed to fetch frames: {e}")
        return []


async def run_vlm_inference(
    frames: list[dict],
    context: str,
    max_ms: float,
) -> dict:
    """
    Send frames + context to model-router for VLM inference.
    Returns structured scene analysis data.

    In the initial scaffold, this returns a stub response.
    Real implementation will call model-router with task_type=vision_analysis.
    """
    # --- STUB: replace with real VLM call via model-router ---
    start = time.perf_counter()

    # Simulate structured output from VLM
    # In production: POST to model-router /v1/chat with vision payload
    await asyncio.sleep(0.05)  # simulate minimal latency

    elapsed_ms = (time.perf_counter() - start) * 1000

    return {
        "summary": f"Scene analysis stub ({len(frames)} frame(s), context: '{context[:50]}...' if context else 'none')",
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
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "service": "perception",
        "version": "2.6.0",
        "inference_status": state.status,
    }


@app.get("/v1/perception/status")
async def get_status():
    return {
        "status": state.status,
        "total_inferences": state.total_inferences,
        "total_errors": state.total_errors,
        "avg_inference_ms": round(state.avg_inference_ms, 1),
        "last_scene_id": state.last_scene.scene_id if state.last_scene else None,
    }


@app.post("/v1/perception/analyze", response_model=SceneAnalysis)
async def analyze(req: PerceptionRequest):
    """
    Trigger scene analysis. Fetches frames from vision-capture,
    runs VLM inference, returns structured output.

    IMPORTANT: recommended_action is NEVER auto-executed.
    """
    if state.status == PerceptionStatus.PROCESSING:
        raise HTTPException(429, "Inference already in progress")

    state.status = PerceptionStatus.PROCESSING
    try:
        # Fetch frames from vision-capture
        frames = await fetch_frames(req.frame_count)
        if not frames:
            state.status = PerceptionStatus.IDLE
            raise HTTPException(
                503,
                "No frames available from vision-capture. "
                "Ensure privacy is enabled and capture mode is active.",
            )

        # Run VLM inference
        result = await run_vlm_inference(frames, req.context, req.max_inference_ms)

        scene = SceneAnalysis(
            scene_id=str(uuid.uuid4()),
            timestamp=time.time(),
            trigger=req.trigger,
            summary=result["summary"],
            entities=[Entity(**e) for e in result.get("entities", [])],
            overall_confidence=result.get("overall_confidence", 0.0),
            recommended_action=result.get("recommended_action"),
            action_requires_confirmation=True,  # ALWAYS
            inference_ms=result.get("inference_ms", 0.0),
            model_used=result.get("model_used"),
        )

        state.record_inference(scene.inference_ms)
        state.last_scene = scene
        state.status = PerceptionStatus.IDLE
        return scene

    except HTTPException:
        state.status = PerceptionStatus.IDLE
        raise
    except Exception as e:
        state.total_errors += 1
        state.status = PerceptionStatus.ERROR
        logger.error(f"Perception error: {e}", exc_info=True)
        raise HTTPException(500, f"Perception pipeline error: {e}")


@app.get("/v1/perception/last")
async def get_last_scene():
    """Retrieve the most recent scene analysis."""
    if state.last_scene is None:
        raise HTTPException(404, "No scene analysis available yet")
    return state.last_scene


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=7070, log_level="info")
