"""
API Gateway — Vision Ingestion & Validation (Stage 4)

Validates incoming vision frames against configurable limits
and tracks per-session rate.  Keeps the session alive on
invalid frames; only rejects the individual frame.
"""

import base64
import logging
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from schemas.vision import (
    ALLOWED_MIME_TYPES,
    DEFAULT_MAX_FRAME_BYTES,
    DEFAULT_MAX_FRAMES_PER_MINUTE,
    DEFAULT_MAX_FRAMES_PER_TURN,
    VisionConfig,
    VisionFrame,
)

logger = logging.getLogger("api-gateway.vision")


class VisionIngestError:
    """Structured rejection for a single frame."""

    def __init__(self, code: str, message: str, frame_id: str = ""):
        self.code = code
        self.message = message
        self.frame_id = frame_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "frame_id": self.frame_id,
        }


class VisionRateLimiter:
    """
    Track frames per session per minute.
    Sliding-window approach: keep timestamps and prune old entries.
    """

    def __init__(self):
        self._windows: Dict[str, List[float]] = defaultdict(list)

    def record(self, session_id: str) -> None:
        self._windows[session_id].append(time.monotonic())

    def count_in_last_minute(self, session_id: str) -> int:
        now = time.monotonic()
        window = self._windows.get(session_id, [])
        # Prune entries older than 60 s
        window = [t for t in window if (now - t) < 60.0]
        self._windows[session_id] = window
        return len(window)

    def cleanup_session(self, session_id: str) -> None:
        self._windows.pop(session_id, None)


# Module-level singleton
_rate_limiter = VisionRateLimiter()


def get_rate_limiter() -> VisionRateLimiter:
    return _rate_limiter


def validate_frame(
    payload: Dict[str, Any],
    session_id: str,
    config: Optional[VisionConfig] = None,
    turn_frame_count: int = 0,
) -> Tuple[Optional[VisionFrame], Optional[VisionIngestError]]:
    """
    Validate a single vision frame payload.

    Returns (frame, None) on success or (None, error) on rejection.
    The session is never killed by a bad frame.
    """
    cfg = config or VisionConfig(enabled=True)

    if not cfg.enabled:
        return None, VisionIngestError(
            "VISION_DISABLED",
            "Vision is not enabled for this session",
        )

    frame_id = payload.get("frame_id") or f"frm_{uuid.uuid4().hex[:12]}"
    mime_type = payload.get("mime_type", "")
    data_b64 = payload.get("data", "")

    # Mime check
    if mime_type not in ALLOWED_MIME_TYPES:
        return None, VisionIngestError(
            "INVALID_MIME_TYPE",
            f"Unsupported mime type: {mime_type}. "
            f"Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
            frame_id,
        )

    # Decode size check
    if not data_b64:
        return None, VisionIngestError(
            "MISSING_DATA",
            "Vision frame payload.data is empty",
            frame_id,
        )

    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception:
        return None, VisionIngestError(
            "INVALID_BASE64",
            "Could not decode base64 image data",
            frame_id,
        )

    size_bytes = len(raw)
    if size_bytes > cfg.max_frame_bytes:
        return None, VisionIngestError(
            "FRAME_TOO_LARGE",
            f"Frame is {size_bytes} bytes; limit is {cfg.max_frame_bytes}",
            frame_id,
        )

    # Rate limit
    rl = get_rate_limiter()
    if rl.count_in_last_minute(session_id) >= cfg.max_frames_per_minute:
        return None, VisionIngestError(
            "RATE_LIMIT_EXCEEDED",
            f"Max {cfg.max_frames_per_minute} frames/min exceeded",
            frame_id,
        )

    # Per-turn limit
    if turn_frame_count >= cfg.max_frames_per_turn:
        return None, VisionIngestError(
            "TURN_FRAME_LIMIT",
            f"Max {cfg.max_frames_per_turn} frames per turn exceeded",
            frame_id,
        )

    rl.record(session_id)

    frame = VisionFrame(
        frame_id=frame_id,
        mime_type=mime_type,
        size_bytes=size_bytes,
        data_b64=data_b64,
    )
    return frame, None
