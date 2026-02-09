"""
Pipecat — Per-Turn Latency Tracker

Records wall-clock timing for each pipeline stage within a single
voice turn.  Designed to be created at turn start, stamped at each
stage boundary, and finalised at turn end.

Usage:
    lat = TurnLatency(session_id="s1", turn_seq=1, trace_id="t1")
    lat.stamp_asr_start()
    ...
    lat.stamp_asr_end()
    lat.stamp_infer_start()
    ...
    lat.stamp_infer_end()
    lat.stamp_tts_start()
    ...
    lat.stamp_tts_end()
    lat.finalise()
    report = lat.to_dict()
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TurnLatency:
    """Wall-clock timing for a single voice turn."""

    session_id: str = ""
    turn_seq: int = 0
    trace_id: str = ""

    # ---- raw monotonic timestamps -----------------------------------------
    turn_start: float = field(default_factory=time.monotonic)

    asr_start: float = 0.0
    asr_end: float = 0.0

    infer_start: float = 0.0
    infer_end: float = 0.0

    tts_start: float = 0.0
    tts_end: float = 0.0

    turn_end: float = 0.0

    # ---- computed durations (ms) — filled by finalise() -------------------
    asr_ms: float = 0.0
    infer_ms: float = 0.0
    tts_ms: float = 0.0
    total_ms: float = 0.0

    # ---- flags ------------------------------------------------------------
    interrupted: bool = False
    timed_out: bool = False
    error: Optional[str] = None

    # ---- stamp helpers ----------------------------------------------------

    def stamp_asr_start(self) -> None:
        self.asr_start = time.monotonic()

    def stamp_asr_end(self) -> None:
        self.asr_end = time.monotonic()

    def stamp_infer_start(self) -> None:
        self.infer_start = time.monotonic()

    def stamp_infer_end(self) -> None:
        self.infer_end = time.monotonic()

    def stamp_tts_start(self) -> None:
        self.tts_start = time.monotonic()

    def stamp_tts_end(self) -> None:
        self.tts_end = time.monotonic()

    def finalise(self) -> None:
        """Compute durations from raw timestamps."""
        self.turn_end = time.monotonic()

        if self.asr_start and self.asr_end:
            self.asr_ms = round((self.asr_end - self.asr_start) * 1000, 1)

        if self.infer_start and self.infer_end:
            self.infer_ms = round((self.infer_end - self.infer_start) * 1000, 1)

        if self.tts_start and self.tts_end:
            self.tts_ms = round((self.tts_end - self.tts_start) * 1000, 1)

        self.total_ms = round((self.turn_end - self.turn_start) * 1000, 1)

    # ---- serialisation ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict of the latency report."""
        return {
            "session_id": self.session_id,
            "turn_seq": self.turn_seq,
            "trace_id": self.trace_id,
            "asr_ms": self.asr_ms,
            "infer_ms": self.infer_ms,
            "tts_ms": self.tts_ms,
            "total_ms": self.total_ms,
            "interrupted": self.interrupted,
            "timed_out": self.timed_out,
            "error": self.error,
        }
