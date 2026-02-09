"""
Pipecat — JSONL Turn Telemetry Logger

Appends one JSON line per completed voice turn to a rolling log file.
Each line captures:
    - session_id, turn_seq, trace_id
    - per-stage latencies (asr_ms, infer_ms, tts_ms, total_ms)
    - outcome flags (interrupted, timed_out, error)
    - wall-clock timestamp

The log file is safe for concurrent appends (one write per line,
no partial-line risk on modern OS with < 4 KB writes).

Usage:
    logger = TurnTelemetryLogger()           # defaults to S:\\logs\\services\\pipecat\\turns.jsonl
    logger.log_turn(latency.to_dict())       # append one line
    recent = logger.recent(n=10)             # read last N entries
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default log path
_DEFAULT_LOG_DIR = r"S:\logs\services\pipecat"
_DEFAULT_LOG_FILE = "turns.jsonl"


class TurnTelemetryLogger:
    """Append-only JSONL logger for voice turn telemetry."""

    def __init__(
        self,
        log_dir: str = _DEFAULT_LOG_DIR,
        log_file: str = _DEFAULT_LOG_FILE,
    ):
        self._log_dir = Path(log_dir)
        self._log_path = self._log_dir / log_file
        self._ensure_dir()
        self._turn_count = 0

    def _ensure_dir(self) -> None:
        """Create log directory if it doesn't exist."""
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error("telemetry: cannot create log dir %s: %s", self._log_dir, e)

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def turn_count(self) -> int:
        """Number of turns logged in this process lifetime."""
        return self._turn_count

    def log_turn(self, turn_data: Dict[str, Any]) -> bool:
        """
        Append a turn record as a single JSON line.

        Args:
            turn_data: Dict from TurnLatency.to_dict() or similar.

        Returns:
            True if the write succeeded.
        """
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **turn_data,
        }

        try:
            line = json.dumps(record, default=str, ensure_ascii=False)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._turn_count += 1
            return True
        except Exception as e:
            logger.error("telemetry: write failed: %s", e)
            return False

    def recent(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        Read the last *n* turn records from the log file.

        Returns:
            List of dicts (most recent last).
        """
        if not self._log_path.exists():
            return []

        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            entries: List[Dict[str, Any]] = []
            for line in lines[-n:]:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return entries
        except Exception as e:
            logger.error("telemetry: read failed: %s", e)
            return []

    def summary(self) -> Dict[str, Any]:
        """
        Compute aggregate stats from the current log file.

        Returns:
            Dict with count, avg/p50/p95/max for total_ms.
        """
        entries = self.recent(n=10000)  # read all
        if not entries:
            return {"count": 0}

        totals = [e.get("total_ms", 0) for e in entries if e.get("total_ms")]
        if not totals:
            return {"count": len(entries), "latency_samples": 0}

        totals.sort()
        count = len(totals)
        avg = sum(totals) / count
        p50 = totals[count // 2]
        p95_idx = min(int(count * 0.95), count - 1)
        p95 = totals[p95_idx]
        mx = totals[-1]

        interrupted = sum(1 for e in entries if e.get("interrupted"))
        errors = sum(1 for e in entries if e.get("error"))

        return {
            "count": len(entries),
            "latency_samples": count,
            "avg_ms": round(avg, 1),
            "p50_ms": round(p50, 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(mx, 1),
            "interrupted_count": interrupted,
            "error_count": errors,
        }
