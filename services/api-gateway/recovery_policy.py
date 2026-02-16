"""
v3.7 M2 — Recovery Policy Table

Deterministic recovery behavior: state + trigger -> action + cooldown.
Restart budget and backoff behavior for self-healing.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.recovery_policy")


class RecoveryTrigger(str, Enum):
    """Trigger conditions that initiate recovery actions."""
    HEALTH_CHECK_FAILED = "health_check_failed"
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    TIMEOUT_EXCEEDED = "timeout_exceeded"
    CONNECTION_REFUSED = "connection_refused"
    BACKPRESSURE_DETECTED = "backpressure_detected"
    DLQ_THRESHOLD_EXCEEDED = "dlq_threshold_exceeded"
    MEMORY_BUDGET_EXCEEDED = "memory_budget_exceeded"
    PROCESS_CRASHED = "process_crashed"


class RecoveryAction(str, Enum):
    """Actions taken in response to recovery triggers."""
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    CIRCUIT_OPEN = "circuit_open"
    FAILOVER_TO_FALLBACK = "failover_to_fallback"
    RESTART_SERVICE = "restart_service"
    DLQ_ENQUEUE = "dlq_enqueue"
    SHED_LOAD = "shed_load"
    ALERT_OPERATOR = "alert_operator"
    NO_ACTION = "no_action"


class ServiceState(str, Enum):
    """Service states that affect recovery behavior."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAILED = "failed"


@dataclass
class RecoveryRule:
    """A single row in the recovery policy table."""
    state: ServiceState
    trigger: RecoveryTrigger
    action: RecoveryAction
    cooldown_seconds: float
    max_retries: int = 3
    backoff_base: float = 1.5
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "trigger": self.trigger.value,
            "action": self.action.value,
            "cooldown_seconds": self.cooldown_seconds,
            "max_retries": self.max_retries,
            "backoff_base": self.backoff_base,
            "description": self.description,
        }


# ── Canonical Recovery Policy Table ──────────────────────────────────────────

RECOVERY_POLICY_TABLE: List[RecoveryRule] = [
    RecoveryRule(
        state=ServiceState.HEALTHY,
        trigger=RecoveryTrigger.HEALTH_CHECK_FAILED,
        action=RecoveryAction.RETRY_WITH_BACKOFF,
        cooldown_seconds=5.0,
        max_retries=3,
        description="Single health check failure from healthy state: retry with backoff",
    ),
    RecoveryRule(
        state=ServiceState.HEALTHY,
        trigger=RecoveryTrigger.TIMEOUT_EXCEEDED,
        action=RecoveryAction.RETRY_WITH_BACKOFF,
        cooldown_seconds=2.0,
        max_retries=2,
        description="Timeout from healthy: fast retry then degrade",
    ),
    RecoveryRule(
        state=ServiceState.HEALTHY,
        trigger=RecoveryTrigger.BACKPRESSURE_DETECTED,
        action=RecoveryAction.SHED_LOAD,
        cooldown_seconds=10.0,
        max_retries=0,
        description="Backpressure from healthy: shed load immediately",
    ),
    RecoveryRule(
        state=ServiceState.DEGRADED,
        trigger=RecoveryTrigger.HEALTH_CHECK_FAILED,
        action=RecoveryAction.CIRCUIT_OPEN,
        cooldown_seconds=30.0,
        max_retries=0,
        description="Continued failures in degraded: open circuit breaker",
    ),
    RecoveryRule(
        state=ServiceState.DEGRADED,
        trigger=RecoveryTrigger.CIRCUIT_BREAKER_TRIPPED,
        action=RecoveryAction.FAILOVER_TO_FALLBACK,
        cooldown_seconds=30.0,
        max_retries=0,
        description="Circuit tripped in degraded: failover to fallback path",
    ),
    RecoveryRule(
        state=ServiceState.DEGRADED,
        trigger=RecoveryTrigger.DLQ_THRESHOLD_EXCEEDED,
        action=RecoveryAction.ALERT_OPERATOR,
        cooldown_seconds=60.0,
        max_retries=0,
        description="DLQ growing in degraded: alert operator for investigation",
    ),
    RecoveryRule(
        state=ServiceState.FAILED,
        trigger=RecoveryTrigger.PROCESS_CRASHED,
        action=RecoveryAction.RESTART_SERVICE,
        cooldown_seconds=60.0,
        max_retries=3,
        backoff_base=2.0,
        description="Process crash in failed: restart with exponential backoff",
    ),
    RecoveryRule(
        state=ServiceState.FAILED,
        trigger=RecoveryTrigger.CONNECTION_REFUSED,
        action=RecoveryAction.DLQ_ENQUEUE,
        cooldown_seconds=0.0,
        max_retries=0,
        description="Connection refused in failed: enqueue to DLQ for later replay",
    ),
    RecoveryRule(
        state=ServiceState.RECOVERING,
        trigger=RecoveryTrigger.HEALTH_CHECK_FAILED,
        action=RecoveryAction.NO_ACTION,
        cooldown_seconds=15.0,
        max_retries=0,
        description="Health check failure during recovery: wait for cooldown",
    ),
    RecoveryRule(
        state=ServiceState.RECOVERING,
        trigger=RecoveryTrigger.TIMEOUT_EXCEEDED,
        action=RecoveryAction.FAILOVER_TO_FALLBACK,
        cooldown_seconds=10.0,
        max_retries=1,
        description="Timeout during recovery: failover with limited retry",
    ),
]


@dataclass
class RestartBudget:
    """Tracks restart attempts to prevent restart storms."""
    max_restarts: int = 5
    window_seconds: float = 300.0  # 5-minute window
    _restart_times: List[float] = field(default_factory=list)

    def can_restart(self) -> bool:
        """Check if a restart is allowed within budget."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        self._restart_times = [t for t in self._restart_times if t > cutoff]
        return len(self._restart_times) < self.max_restarts

    def record_restart(self) -> None:
        """Record a restart attempt."""
        self._restart_times.append(time.monotonic())

    @property
    def remaining(self) -> int:
        """Number of restarts remaining in the current window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        recent = sum(1 for t in self._restart_times if t > cutoff)
        return max(0, self.max_restarts - recent)

    @property
    def exhausted(self) -> bool:
        return self.remaining == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_restarts": self.max_restarts,
            "window_seconds": self.window_seconds,
            "remaining": self.remaining,
            "exhausted": self.exhausted,
        }


class RecoveryPolicyEngine:
    """
    Looks up the correct recovery action for a given (state, trigger) pair.
    Enforces cooldowns and restart budgets.
    """

    def __init__(self, policy_table: Optional[List[RecoveryRule]] = None):
        self._table = policy_table or RECOVERY_POLICY_TABLE
        self._cooldowns: Dict[str, float] = {}  # key -> last_action_time
        self._restart_budgets: Dict[str, RestartBudget] = {}
        self._decision_count: int = 0
        self._decision_log: List[Dict[str, Any]] = []

    def lookup(self, state: ServiceState, trigger: RecoveryTrigger) -> Optional[RecoveryRule]:
        """Find the matching recovery rule for a (state, trigger) pair."""
        for rule in self._table:
            if rule.state == state and rule.trigger == trigger:
                return rule
        return None

    def decide(
        self,
        service_name: str,
        state: ServiceState,
        trigger: RecoveryTrigger,
        correlation_id: str = "",
    ) -> Dict[str, Any]:
        """
        Make a deterministic recovery decision.

        Returns dict with:
            action: RecoveryAction value
            allowed: bool (False if in cooldown or budget exhausted)
            rule: the matching RecoveryRule dict (or None)
            reason: why the decision was made
        """
        self._decision_count += 1
        rule = self.lookup(state, trigger)

        if rule is None:
            decision = {
                "action": RecoveryAction.NO_ACTION.value,
                "allowed": False,
                "rule": None,
                "reason": f"No rule for ({state.value}, {trigger.value})",
                "correlation_id": correlation_id,
            }
            self._log_decision(service_name, decision)
            return decision

        # Check cooldown
        cooldown_key = f"{service_name}:{state.value}:{trigger.value}"
        now = time.monotonic()
        last_action = self._cooldowns.get(cooldown_key, 0)
        if now - last_action < rule.cooldown_seconds:
            remaining = rule.cooldown_seconds - (now - last_action)
            decision = {
                "action": rule.action.value,
                "allowed": False,
                "rule": rule.to_dict(),
                "reason": f"Cooldown active ({remaining:.1f}s remaining)",
                "correlation_id": correlation_id,
            }
            self._log_decision(service_name, decision)
            return decision

        # Check restart budget
        if rule.action == RecoveryAction.RESTART_SERVICE:
            budget = self._restart_budgets.setdefault(
                service_name, RestartBudget()
            )
            if not budget.can_restart():
                decision = {
                    "action": rule.action.value,
                    "allowed": False,
                    "rule": rule.to_dict(),
                    "reason": f"Restart budget exhausted ({budget.to_dict()})",
                    "correlation_id": correlation_id,
                }
                self._log_decision(service_name, decision)
                return decision
            budget.record_restart()

        # Action allowed
        self._cooldowns[cooldown_key] = now
        decision = {
            "action": rule.action.value,
            "allowed": True,
            "rule": rule.to_dict(),
            "reason": rule.description,
            "correlation_id": correlation_id,
        }
        self._log_decision(service_name, decision)
        return decision

    def _log_decision(self, service_name: str, decision: Dict[str, Any]) -> None:
        """Record decision for auditability."""
        entry = {
            "service": service_name,
            "timestamp": time.monotonic(),
            **decision,
        }
        self._decision_log.append(entry)
        if len(self._decision_log) > 1000:
            self._decision_log = self._decision_log[-1000:]

    def get_policy_table(self) -> List[Dict[str, Any]]:
        """Export the full policy table for operator review."""
        return [r.to_dict() for r in self._table]

    def get_decision_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent decision log entries."""
        return self._decision_log[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_rules": len(self._table),
            "total_decisions": self._decision_count,
            "active_cooldowns": len(self._cooldowns),
            "restart_budgets": {
                k: v.to_dict() for k, v in self._restart_budgets.items()
            },
        }
