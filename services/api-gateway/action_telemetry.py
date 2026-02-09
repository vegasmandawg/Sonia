"""
Stage 5 — Action Telemetry
Structured telemetry collector for action pipeline events.
Writes JSONL to S:\\logs\\gateway\\actions_YYYYMMDD.jsonl
"""

import time
from typing import Any, Dict, Optional
from datetime import datetime
from jsonl_logger import JsonlLogger


class ActionTelemetryCollector:
    """
    Collects and emits structured telemetry for action lifecycle events.
    Each event is a single JSONL line in the actions log.
    """

    def __init__(self):
        self._logger = JsonlLogger("actions")

    def emit(self, action_id: str, event: str, **fields):
        """Emit a telemetry event."""
        self._logger.log({
            "action_id": action_id,
            "event": event,
            **fields,
        })

    def plan_started(self, action_id: str, intent: str, correlation_id: str,
                     dry_run: bool = False):
        self.emit(action_id, "plan.started",
                  intent=intent, correlation_id=correlation_id, dry_run=dry_run)

    def plan_completed(self, action_id: str, risk_level: str,
                       requires_confirmation: bool, plan_ms: float):
        self.emit(action_id, "plan.completed",
                  risk_level=risk_level,
                  requires_confirmation=requires_confirmation,
                  plan_ms=plan_ms)

    def validation_passed(self, action_id: str, checks_passed: int,
                          checks_total: int, validate_ms: float):
        self.emit(action_id, "validation.passed",
                  checks_passed=checks_passed,
                  checks_total=checks_total,
                  validate_ms=validate_ms)

    def validation_failed(self, action_id: str, reason: str, validate_ms: float):
        self.emit(action_id, "validation.failed",
                  reason=reason, validate_ms=validate_ms)

    def execution_started(self, action_id: str, intent: str, attempt: int = 0):
        self.emit(action_id, "execution.started",
                  intent=intent, attempt=attempt)

    def execution_succeeded(self, action_id: str, duration_ms: float,
                            retries_used: int):
        self.emit(action_id, "execution.succeeded",
                  duration_ms=duration_ms, retries_used=retries_used)

    def execution_failed(self, action_id: str, error_code: str,
                         error_message: str, duration_ms: float,
                         retries_used: int):
        self.emit(action_id, "execution.failed",
                  error_code=error_code, error_message=error_message,
                  duration_ms=duration_ms, retries_used=retries_used)

    def execution_timeout(self, action_id: str, duration_ms: float,
                          retries_used: int):
        self.emit(action_id, "execution.timeout",
                  duration_ms=duration_ms, retries_used=retries_used)

    def approval_requested(self, action_id: str, risk_level: str):
        self.emit(action_id, "approval.requested", risk_level=risk_level)

    def approval_granted(self, action_id: str):
        self.emit(action_id, "approval.granted")

    def approval_denied(self, action_id: str):
        self.emit(action_id, "approval.denied")

    def verification_passed(self, action_id: str, verify_ms: float):
        self.emit(action_id, "verification.passed", verify_ms=verify_ms)

    def verification_failed(self, action_id: str, reason: str, verify_ms: float):
        self.emit(action_id, "verification.failed",
                  reason=reason, verify_ms=verify_ms)

    def lifecycle_complete(self, action_id: str, final_state: str,
                           total_ms: float):
        self.emit(action_id, "lifecycle.complete",
                  final_state=final_state, total_ms=total_ms)


# ── Singleton ────────────────────────────────────────────────────────────────

_collector: Optional[ActionTelemetryCollector] = None


def get_action_telemetry() -> ActionTelemetryCollector:
    global _collector
    if _collector is None:
        _collector = ActionTelemetryCollector()
    return _collector
