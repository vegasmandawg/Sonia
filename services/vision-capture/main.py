"""
Vision Capture Service — v2.6 Track B

Camera capture service with RAM ring buffer, ambient/active modes,
and strict privacy controls.

Runs as a FastAPI service on port 7060.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("vision-capture")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RING_BUFFER_MAX_FRAMES = 300       # ~30 sec at 10 fps
AMBIENT_FPS = 1.0                  # 1 frame/sec in ambient mode
ACTIVE_FPS = 10.0                  # 10 fps in active mode
AMBIENT_RESOLUTION = (320, 240)
ACTIVE_RESOLUTION = (640, 480)
MAX_FRAME_BYTES = 1 * 1024 * 1024  # 1 MB


class CaptureMode(str, Enum):
    OFF = "off"
    AMBIENT = "ambient"
    ACTIVE = "active"


class PrivacyState(str, Enum):
    ENABLED = "enabled"    # capture allowed
    DISABLED = "disabled"  # all capture blocked


# ---------------------------------------------------------------------------
# Frame storage
# ---------------------------------------------------------------------------

@dataclass
class Frame:
    frame_id: str
    timestamp: float
    width: int
    height: int
    data_b64: str
    size_bytes: int
    mode: CaptureMode


class RingBuffer:
    """Thread-safe-ish ring buffer backed by deque."""

    def __init__(self, maxlen: int = RING_BUFFER_MAX_FRAMES):
        self._buf: deque[Frame] = deque(maxlen=maxlen)

    def push(self, frame: Frame) -> None:
        self._buf.append(frame)

    def latest(self, n: int = 1) -> list[Frame]:
        items = list(self._buf)
        return items[-n:] if n <= len(items) else items

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)

    @property
    def duration_seconds(self) -> float:
        if len(self._buf) < 2:
            return 0.0
        return self._buf[-1].timestamp - self._buf[0].timestamp


# ---------------------------------------------------------------------------
# Service state
# ---------------------------------------------------------------------------

class VisionCaptureState:
    def __init__(self):
        self.privacy: PrivacyState = PrivacyState.DISABLED  # default: OFF
        self.mode: CaptureMode = CaptureMode.OFF
        self.buffer: RingBuffer = RingBuffer()
        self.frames_captured: int = 0
        self.frames_rejected: int = 0
        self.last_frame_time: float = 0.0
        self._capture_task: Optional[asyncio.Task] = None

    @property
    def capture_allowed(self) -> bool:
        return (
            self.privacy == PrivacyState.ENABLED
            and self.mode != CaptureMode.OFF
        )

    @property
    def target_fps(self) -> float:
        if self.mode == CaptureMode.ACTIVE:
            return ACTIVE_FPS
        if self.mode == CaptureMode.AMBIENT:
            return AMBIENT_FPS
        return 0.0

    @property
    def target_resolution(self) -> tuple[int, int]:
        if self.mode == CaptureMode.ACTIVE:
            return ACTIVE_RESOLUTION
        return AMBIENT_RESOLUTION


state = VisionCaptureState()

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Vision capture service starting (privacy=disabled, mode=off)")
    yield
    # Cleanup
    if state._capture_task and not state._capture_task.done():
        state._capture_task.cancel()
    state.buffer.clear()
    logger.info("Vision capture service stopped")


app = FastAPI(title="Vision Capture Service", version="2.6.0", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PrivacyToggleRequest(BaseModel):
    state: PrivacyState


class ModeChangeRequest(BaseModel):
    mode: CaptureMode


class IngestFrameRequest(BaseModel):
    """External frame push (from webcam capture client)."""
    data_b64: str
    width: int = 640
    height: int = 480
    timestamp: Optional[float] = None


class CaptureStatus(BaseModel):
    privacy: PrivacyState
    mode: CaptureMode
    buffer_frames: int
    buffer_duration_seconds: float
    frames_captured: int
    frames_rejected: int
    target_fps: float
    target_resolution: list[int]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "vision-capture", "version": "2.6.0"}


@app.get("/v1/vision/status", response_model=CaptureStatus)
async def get_status():
    return CaptureStatus(
        privacy=state.privacy,
        mode=state.mode,
        buffer_frames=len(state.buffer),
        buffer_duration_seconds=round(state.buffer.duration_seconds, 2),
        frames_captured=state.frames_captured,
        frames_rejected=state.frames_rejected,
        target_fps=state.target_fps,
        target_resolution=list(state.target_resolution),
    )


@app.post("/v1/vision/privacy")
async def set_privacy(req: PrivacyToggleRequest):
    """Toggle privacy state. When disabled, buffer is cleared immediately."""
    old = state.privacy
    state.privacy = req.state
    if req.state == PrivacyState.DISABLED:
        state.buffer.clear()
        state.mode = CaptureMode.OFF
        logger.info("Privacy disabled -> buffer cleared, capture off")
    else:
        logger.info("Privacy enabled -> capture can be activated")
    return {"old": old, "new": state.privacy, "buffer_cleared": req.state == PrivacyState.DISABLED}


@app.post("/v1/vision/mode")
async def set_mode(req: ModeChangeRequest):
    """Switch between off/ambient/active. Requires privacy=enabled."""
    if state.privacy == PrivacyState.DISABLED and req.mode != CaptureMode.OFF:
        raise HTTPException(400, "Cannot enable capture while privacy is disabled")
    old = state.mode
    state.mode = req.mode
    if req.mode == CaptureMode.OFF:
        state.buffer.clear()
    logger.info(f"Mode changed: {old} -> {req.mode}")
    return {"old": old, "new": state.mode}


@app.post("/v1/vision/frames")
async def ingest_frame(req: IngestFrameRequest):
    """Push a frame into the ring buffer. Rejected if privacy off or over size limit."""
    # Privacy hard gate
    if state.privacy == PrivacyState.DISABLED:
        state.frames_rejected += 1
        raise HTTPException(403, "PRIVACY_DISABLED: no frames accepted")

    if state.mode == CaptureMode.OFF:
        state.frames_rejected += 1
        raise HTTPException(400, "CAPTURE_OFF: activate ambient or active mode first")

    # Size check
    raw = base64.b64decode(req.data_b64)
    if len(raw) > MAX_FRAME_BYTES:
        state.frames_rejected += 1
        raise HTTPException(413, f"Frame too large: {len(raw)} bytes (max {MAX_FRAME_BYTES})")

    # Rate limit check
    now = req.timestamp or time.time()
    min_interval = 1.0 / state.target_fps
    if state.last_frame_time and (now - state.last_frame_time) < min_interval * 0.8:
        state.frames_rejected += 1
        raise HTTPException(429, "Rate limit: frames arriving too fast")

    frame = Frame(
        frame_id=str(uuid.uuid4()),
        timestamp=now,
        width=req.width,
        height=req.height,
        data_b64=req.data_b64,
        size_bytes=len(raw),
        mode=state.mode,
    )
    state.buffer.push(frame)
    state.frames_captured += 1
    state.last_frame_time = now

    return {
        "frame_id": frame.frame_id,
        "buffer_frames": len(state.buffer),
        "buffer_duration_seconds": round(state.buffer.duration_seconds, 2),
    }


@app.get("/v1/vision/frames/latest")
async def get_latest_frames(n: int = 1):
    """Retrieve the N most recent frames from the ring buffer."""
    if state.privacy == PrivacyState.DISABLED:
        raise HTTPException(403, "PRIVACY_DISABLED: cannot read frames")

    frames = state.buffer.latest(n)
    return {
        "count": len(frames),
        "frames": [
            {
                "frame_id": f.frame_id,
                "timestamp": f.timestamp,
                "width": f.width,
                "height": f.height,
                "size_bytes": f.size_bytes,
                "mode": f.mode,
                "data_b64": f.data_b64,
            }
            for f in frames
        ],
    }


@app.delete("/v1/vision/buffer")
async def clear_buffer():
    """Explicitly clear the ring buffer."""
    count = len(state.buffer)
    state.buffer.clear()
    return {"cleared_frames": count}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=7060, log_level="info")
