"""
Stage 5 M3 — Action Audit Trail
Structured audit logger for all action lifecycle events.
Writes a per-action audit record with full timeline for operator review.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from jsonl_logger import JsonlLogger


class AuditEntry:
    """A single audit event within an action's lifecycle."""

    def __init__(self, phase: str, status: str, detail: Optional[str] = None,
                 duration_ms: float = 0.0, **extra):
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.phase = phase
        self.status = status
        self.detail = detail
        self.duration_ms = duration_ms
        self.extra = extra

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "timestamp": self.timestamp,
            "phase": self.phase,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }
        if self.detail:
            d["detail"] = self.detail
        d.update(self.extra)
        return d


class ActionAuditTrail:
    """
    Collects audit entries for a single action's lifecycle.
    Written to JSONL log when the lifecycle completes.
    """

    def __init__(self, action_id: str, intent: str, correlation_id: Optional[str] = None):
        self.action_id = action_id
        self.intent = intent
        self.correlation_id = correlation_id
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self._entries: List[AuditEntry] = []

    def record(self, phase: str, status: str, detail: Optional[str] = None,
               duration_ms: float = 0.0, **extra):
        """Add an audit entry."""
        self._entries.append(AuditEntry(phase, status, detail, duration_ms, **extra))

    def entries(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._entries]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "intent": self.intent,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at,
            "events": self.entries(),
            "event_count": len(self._entries),
        }


class AuditLogger:
    """
    Singleton audit logger that persists completed audit trails to JSONL.
    Also keeps the last N trails in memory for API inspection.
    """

    MAX_IN_MEMORY = 500

    def __init__(self):
        self._logger = JsonlLogger("audit")
        self._trails: Dict[str, ActionAuditTrail] = {}

    def create_trail(self, action_id: str, intent: str,
                     correlation_id: Optional[str] = None) -> ActionAuditTrail:
        """Create and register a new audit trail."""
        trail = ActionAuditTrail(action_id, intent, correlation_id)
        self._trails[action_id] = trail
        # Evict oldest if over limit
        if len(self._trails) > self.MAX_IN_MEMORY:
            oldest_key = min(self._trails,
                             key=lambda k: self._trails[k].created_at)
            self._trails.pop(oldest_key, None)
        return trail

    def get_trail(self, action_id: str) -> Optional[ActionAuditTrail]:
        return self._trails.get(action_id)

    def flush_trail(self, action_id: str):
        """Write completed trail to JSONL log."""
        trail = self._trails.get(action_id)
        if trail:
            self._logger.log(trail.to_dict())

    def list_trails(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """List recent audit trails."""
        trails = sorted(self._trails.values(),
                        key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in trails[offset:offset + limit]]

    def count(self) -> int:
        return len(self._trails)


# ── Singleton ────────────────────────────────────────────────────────────────

_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
