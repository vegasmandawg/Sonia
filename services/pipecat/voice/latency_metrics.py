"""Latency instrumentation for voice turn lifecycle (G18).

Event-native latency measurement: stamps recorded at event ingestion,
not via external stopwatches.

Metrics:
    warm_path_ms: t_first_emit_ns - t_detect_ns (speech detected -> first output)

Gate G18 threshold: p95 warm-path <= 1200 ms.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional


@dataclass
class TurnLatency:
    """Latency record for a single turn."""
    session_id: str
    turn_id: str
    t_detect_ns: Optional[int] = None
    t_first_emit_ns: Optional[int] = None
    finalized: bool = False

    @property
    def warm_path_ns(self) -> Optional[int]:
        """Time from speech detection to first assistant output (nanoseconds)."""
        if self.t_detect_ns is not None and self.t_first_emit_ns is not None:
            return self.t_first_emit_ns - self.t_detect_ns
        return None

    @property
    def warm_path_ms(self) -> Optional[float]:
        """Warm-path latency in milliseconds."""
        ns = self.warm_path_ns
        return ns / 1_000_000 if ns is not None else None


class LatencyCollector:
    """Collects and computes latency percentiles for voice turns.

    Thread-safe. Stores per-turn latency records and computes
    aggregate statistics over a sliding window.
    """

    # G18 threshold: p95 warm-path <= 1200 ms
    G18_P95_THRESHOLD_MS: float = 1200.0

    def __init__(self, max_window: int = 1000) -> None:
        self._lock = Lock()
        self._records: dict[tuple[str, str], TurnLatency] = {}
        self._finalized: list[TurnLatency] = []
        self._max_window = max_window

    def record_turn_start(self, session_id: str, turn_id: str, t_detect_ns: int) -> None:
        """Record when voice activity confirms turn start."""
        with self._lock:
            key = (session_id, turn_id)
            rec = self._records.get(key)
            if rec is None:
                rec = TurnLatency(session_id=session_id, turn_id=turn_id)
                self._records[key] = rec
            rec.t_detect_ns = t_detect_ns

    def record_first_emit(self, session_id: str, turn_id: str, t_first_emit_ns: int) -> None:
        """Record when first assistant output is emitted (token/audio chunk)."""
        with self._lock:
            key = (session_id, turn_id)
            rec = self._records.get(key)
            if rec is None:
                rec = TurnLatency(session_id=session_id, turn_id=turn_id)
                self._records[key] = rec
            # Only record the first emit
            if rec.t_first_emit_ns is None:
                rec.t_first_emit_ns = t_first_emit_ns

    def finalize_turn(self, session_id: str, turn_id: str) -> Optional[TurnLatency]:
        """Finalize a turn and move it to the completed window."""
        with self._lock:
            key = (session_id, turn_id)
            rec = self._records.pop(key, None)
            if rec is not None and not rec.finalized:
                rec.finalized = True
                self._finalized.append(rec)
                # Trim window
                if len(self._finalized) > self._max_window:
                    self._finalized = self._finalized[-self._max_window:]
            return rec

    def compute_percentiles(self, window: Optional[int] = None) -> dict:
        """Compute latency percentiles over finalized turns.

        Returns:
            {
                "count": int,
                "p50_ms": float or None,
                "p95_ms": float or None,
                "p99_ms": float or None,
                "g18_pass": bool,
            }
        """
        with self._lock:
            records = list(self._finalized)

        if window is not None:
            records = records[-window:]

        latencies_ms = [
            r.warm_path_ms for r in records
            if r.warm_path_ms is not None
        ]

        if not latencies_ms:
            return {
                "count": 0,
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "g18_pass": False,
            }

        latencies_ms.sort()
        n = len(latencies_ms)

        def percentile(data: list[float], pct: float) -> float:
            k = (pct / 100) * (len(data) - 1)
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            d = k - f
            return data[f] + d * (data[c] - data[f])

        p50 = percentile(latencies_ms, 50)
        p95 = percentile(latencies_ms, 95)
        p99 = percentile(latencies_ms, 99)

        return {
            "count": n,
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "g18_pass": p95 <= self.G18_P95_THRESHOLD_MS,
        }

    @property
    def pending_count(self) -> int:
        """Number of turns that have started but not finalized."""
        with self._lock:
            return len(self._records)

    @property
    def finalized_count(self) -> int:
        """Number of finalized turns in the window."""
        with self._lock:
            return len(self._finalized)
