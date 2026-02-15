"""
Vision Capture Service -- v2.6 Track B (production-hardened)

Camera capture service with RAM ring buffer, ambient/active modes,
and strict privacy controls. Privacy OFF by default. No auto-enable on restart.

Zero-frame invariant: when privacy is disabled, the buffer is cleared,
writes are rejected (403), reads return empty/forbidden, and no stale
data can leak through any endpoint.

Port: 7060 | Health: /healthz
"""

from __future__ import annotations

import base64
import logging
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from version import SONIA_VERSION, SONIA_CONTRACT

logger = logging.getLogger("vision-capture")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RING_BUFFER_MAX_FRAMES = 300
AMBIENT_FPS = 1.0
ACTIVE_FPS = 10.0
AMBIENT_RESOLUTION = (320, 240)
ACTIVE_RESOLUTION = (640, 480)
MAX_FRAME_BYTES = 1 * 1024 * 1024


class CaptureMode(str, Enum):
    OFF = "off"
    AMBIENT = "ambient"
    ACTIVE = "active"


class PrivacyState(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


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
    def __init__(self, maxlen: int = RING_BUFFER_MAX_FRAMES):
        self._buf: deque[Frame] = deque(maxlen=maxlen)

    def push(self, frame: Frame) -> None:
        self._buf.append(frame)

    def latest(self, n: int = 1) -> list[Frame]:
        items = list(self._buf)
        return items[-n:] if n <= len(items) else items

    def clear(self) -> int:
        count = len(self._buf)
        self._buf.clear()
        return count

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
        self.privacy: PrivacyState = PrivacyState.DISABLED
        self.mode: CaptureMode = CaptureMode.OFF
        self.buffer: RingBuffer = RingBuffer()
        self.frames_captured: int = 0
        self.frames_rejected: int = 0
        self.frames_rejected_privacy: int = 0
        self.frames_rejected_mode: int = 0
        self.frames_rejected_size: int = 0
        self.frames_rejected_rate: int = 0
        self.last_frame_time: float = 0.0
        self.privacy_toggle_count: int = 0
        self.mode_toggle_count: int = 0
        self.started_at: float = time.time()

    @property
    def capture_allowed(self) -> bool:
        return self.privacy == PrivacyState.ENABLED and self.mode != CaptureMode.OFF

    @property
    def target_fps(self) -> float:
        if self.mode == CaptureMode.ACTIVE:
            return ACTIVE_FPS
        if self.mode == CaptureMode.AMBIENT:
            return AMBIENT_FPS
        return 0.0

    @property
    def target_resolution(self) -> tuple:
        if self.mode == CaptureMode.ACTIVE:
            return ACTIVE_RESOLUTION
        return AMBIENT_RESOLUTION

    def enforce_privacy_off(self) -> int:
        cleared = self.buffer.clear()
        self.mode = CaptureMode.OFF
        self.last_frame_time = 0.0
        return cleared


state = VisionCaptureState()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Vision capture starting (privacy=DISABLED, mode=OFF)")
    state.enforce_privacy_off()
    yield
    state.enforce_privacy_off()
    logger.info("Vision capture stopped, buffer cleared")


app = FastAPI(title="Vision Capture Service", version=SONIA_VERSION, lifespan=lifespan)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PrivacyToggleRequest(BaseModel):
    state: PrivacyState


class ModeChangeRequest(BaseModel):
    mode: CaptureMode


class IngestFrameRequest(BaseModel):
    data_b64: str
    width: int = 640
    height: int = 480
    timestamp: Optional[float] = None


# ---------------------------------------------------------------------------
# Routes: health
# ---------------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "service": "vision-capture",
        "version": SONIA_VERSION,
        "contract_version": SONIA_CONTRACT,
        "privacy": state.privacy.value,
        "mode": state.mode.value,
        "buffer_frames": len(state.buffer),
    }


@app.get("/health")
async def health_alias():
    return await healthz()


# ---------------------------------------------------------------------------
# Routes: privacy control
# ---------------------------------------------------------------------------

@app.get("/v1/vision/privacy/status")
async def get_privacy_status():
    return {
        "privacy": state.privacy.value,
        "capture_allowed": state.capture_allowed,
        "mode": state.mode.value,
        "buffer_frames": len(state.buffer),
        "toggle_count": state.privacy_toggle_count,
        "zero_frame_enforced": state.privacy == PrivacyState.DISABLED,
    }


@app.post("/v1/vision/privacy/enable")
async def enable_privacy():
    old = state.privacy
    state.privacy = PrivacyState.ENABLED
    state.privacy_toggle_count += 1
    logger.info("Privacy ENABLED")
    return {"old": old.value, "new": state.privacy.value, "mode": state.mode.value}


@app.post("/v1/vision/privacy/disable")
async def disable_privacy():
    old = state.privacy
    state.privacy = PrivacyState.DISABLED
    state.privacy_toggle_count += 1
    cleared = state.enforce_privacy_off()
    logger.info(f"Privacy DISABLED -> cleared {cleared} frames, mode OFF")
    return {
        "old": old.value,
        "new": state.privacy.value,
        "buffer_cleared": cleared,
        "mode": state.mode.value,
    }


@app.post("/v1/vision/privacy")
async def set_privacy(req: PrivacyToggleRequest):
    if req.state == PrivacyState.ENABLED:
        return await enable_privacy()
    return await disable_privacy()


# ---------------------------------------------------------------------------
# Routes: mode control
# ---------------------------------------------------------------------------

@app.post("/v1/vision/mode/set")
async def set_mode_explicit(req: ModeChangeRequest):
    if state.privacy == PrivacyState.DISABLED and req.mode != CaptureMode.OFF:
        raise HTTPException(400, "PRIVACY_DISABLED: cannot enable capture")
    old = state.mode
    state.mode = req.mode
    state.mode_toggle_count += 1
    if req.mode == CaptureMode.OFF:
        state.buffer.clear()
    return {"old": old.value, "new": state.mode.value}


@app.post("/v1/vision/mode")
async def set_mode(req: ModeChangeRequest):
    return await set_mode_explicit(req)


# ---------------------------------------------------------------------------
# Routes: buffer stats
# ---------------------------------------------------------------------------

@app.get("/v1/vision/buffer/stats")
async def buffer_stats():
    return {
        "frames": len(state.buffer),
        "duration_seconds": round(state.buffer.duration_seconds, 2),
        "max_frames": RING_BUFFER_MAX_FRAMES,
        "privacy": state.privacy.value,
        "mode": state.mode.value,
    }


# ---------------------------------------------------------------------------
# Routes: frame ingestion
# ---------------------------------------------------------------------------

@app.post("/v1/vision/frames")
async def ingest_frame(req: IngestFrameRequest):
    # Privacy hard gate (first check, always)
    if state.privacy == PrivacyState.DISABLED:
        state.frames_rejected += 1
        state.frames_rejected_privacy += 1
        raise HTTPException(403, "PRIVACY_DISABLED: no frames accepted")

    if state.mode == CaptureMode.OFF:
        state.frames_rejected += 1
        state.frames_rejected_mode += 1
        raise HTTPException(400, "CAPTURE_OFF: activate ambient or active mode first")

    try:
        raw = base64.b64decode(req.data_b64)
    except Exception:
        state.frames_rejected += 1
        raise HTTPException(400, "INVALID_BASE64: could not decode frame data")

    if len(raw) > MAX_FRAME_BYTES:
        state.frames_rejected += 1
        state.frames_rejected_size += 1
        raise HTTPException(413, f"FRAME_TOO_LARGE: {len(raw)} bytes (max {MAX_FRAME_BYTES})")

    now = req.timestamp or time.time()
    min_interval = 1.0 / state.target_fps if state.target_fps > 0 else 0
    if min_interval > 0 and state.last_frame_time and (now - state.last_frame_time) < min_interval * 0.8:
        state.frames_rejected += 1
        state.frames_rejected_rate += 1
        raise HTTPException(429, "RATE_LIMITED: frames arriving too fast")

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


# ---------------------------------------------------------------------------
# Routes: frame retrieval (zero-frame on privacy off)
# ---------------------------------------------------------------------------

@app.get("/v1/vision/frames/latest")
async def get_latest_frames(n: int = 1):
    """Returns EMPTY when privacy disabled -- never stale data."""
    if state.privacy == PrivacyState.DISABLED:
        return {"count": 0, "frames": [], "privacy": "disabled"}
    if state.mode == CaptureMode.OFF:
        return {"count": 0, "frames": [], "mode": "off"}
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
                "mode": f.mode.value,
                "data_b64": f.data_b64,
            }
            for f in frames
        ],
    }


@app.get("/v1/vision/frame/latest")
async def get_single_latest():
    """Single frame endpoint. Denied when privacy off."""
    if state.privacy == PrivacyState.DISABLED:
        raise HTTPException(403, "PRIVACY_DISABLED: cannot read frames")
    frames = state.buffer.latest(1)
    if not frames:
        raise HTTPException(404, "NO_FRAMES: buffer is empty")
    f = frames[0]
    return {
        "frame_id": f.frame_id,
        "timestamp": f.timestamp,
        "width": f.width,
        "height": f.height,
        "size_bytes": f.size_bytes,
        "mode": f.mode.value,
        "data_b64": f.data_b64,
    }


@app.delete("/v1/vision/buffer")
async def clear_buffer():
    count = state.buffer.clear()
    return {"cleared_frames": count}


# ---------------------------------------------------------------------------
# Routes: full status
# ---------------------------------------------------------------------------

@app.get("/v1/vision/status")
async def get_status():
    return {
        "privacy": state.privacy.value,
        "mode": state.mode.value,
        "capture_allowed": state.capture_allowed,
        "buffer_frames": len(state.buffer),
        "buffer_duration_seconds": round(state.buffer.duration_seconds, 2),
        "frames_captured": state.frames_captured,
        "frames_rejected": state.frames_rejected,
        "frames_rejected_privacy": state.frames_rejected_privacy,
        "frames_rejected_mode": state.frames_rejected_mode,
        "frames_rejected_size": state.frames_rejected_size,
        "frames_rejected_rate": state.frames_rejected_rate,
        "target_fps": state.target_fps,
        "target_resolution": list(state.target_resolution),
        "privacy_toggle_count": state.privacy_toggle_count,
        "mode_toggle_count": state.mode_toggle_count,
        "uptime_seconds": round(time.time() - state.started_at, 1),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=7060, log_level="info")
