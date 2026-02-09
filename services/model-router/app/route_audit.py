"""
Model Router - Route Audit Logger

Writes JSONL route logs to a persistent file for auditability.
Every routing decision is recorded with trace_id, turn_id, requested
profile, selected backend, fallback chain, reason code, latency, and
outcome.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.routing_engine import RouteDecision

logger = logging.getLogger("model-router.route-audit")

# Default log path
DEFAULT_AUDIT_PATH = r"S:\logs\services\model-router\routes.jsonl"


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------

@dataclass
class AuditRecord:
    """A single auditable route event."""
    trace_id: str
    turn_id: str
    requested_profile: str
    selected_backend: Optional[str]
    fallback_chain: List[str]
    reason_code: str
    latency_ms: float = 0.0
    outcome: str = "pending"  # pending | success | failure
    skipped: List[Dict[str, str]] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "turn_id": self.turn_id,
            "requested_profile": self.requested_profile,
            "selected_backend": self.selected_backend,
            "fallback_chain": self.fallback_chain,
            "reason_code": self.reason_code,
            "latency_ms": round(self.latency_ms, 2),
            "outcome": self.outcome,
            "skipped": self.skipped,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------

class RouteAuditLogger:
    """
    Thread-safe JSONL audit logger.

    Writes one JSON object per line to the audit file.  Buffers writes
    in memory and flushes after each record for durability.
    """

    def __init__(self, path: Optional[str] = None):
        self._path = Path(path or DEFAULT_AUDIT_PATH)
        self._lock = threading.Lock()
        self._record_count = 0
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Create parent directory if needed."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("audit: cannot create dir %s: %s", self._path.parent, e)

    # ---- write from RouteDecision -----------------------------------------

    def log_decision(
        self,
        decision: RouteDecision,
        turn_id: str = "",
        latency_ms: float = 0.0,
        outcome: str = "routed",
    ) -> AuditRecord:
        """Create an AuditRecord from a RouteDecision and write it."""
        record = AuditRecord(
            trace_id=decision.trace_id,
            turn_id=turn_id,
            requested_profile=decision.profile_name,
            selected_backend=decision.selected_backend,
            fallback_chain=decision.fallback_chain,
            reason_code=decision.reason_code,
            latency_ms=latency_ms,
            outcome=outcome,
            skipped=decision.skipped,
        )
        self._write(record)
        return record

    # ---- direct write -----------------------------------------------------

    def log_record(self, record: AuditRecord) -> None:
        """Write an AuditRecord directly."""
        self._write(record)

    # ---- internal ---------------------------------------------------------

    def _write(self, record: AuditRecord) -> None:
        """Serialise and append one record to the audit file."""
        line = json.dumps(record.to_dict(), separators=(",", ":"))
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                self._record_count += 1
            except OSError as e:
                logger.error("audit: write failed: %s", e)

    # ---- queries ----------------------------------------------------------

    def read_recent(self, n: int = 20) -> List[Dict[str, Any]]:
        """Read the last *n* records from the audit file."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            tail = lines[-n:] if len(lines) > n else lines
            return [json.loads(line) for line in tail if line.strip()]
        except (OSError, json.JSONDecodeError):
            return []

    @property
    def record_count(self) -> int:
        return self._record_count

    @property
    def path(self) -> str:
        return str(self._path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "records_written": self._record_count,
        }
