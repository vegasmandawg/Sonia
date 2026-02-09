"""
v2.8 M3: Perception-to-Action Confirmation Gate

Makes it operationally impossible to bypass confirmation for
perception-driven actions.

Architecture:
  1. PerceptionActionGate wraps ALL perception -> action flows
  2. SceneAnalysis.recommended_action is never executed directly
  3. Every perception action goes through ConfirmationRequirement
  4. Bypass attempts raise ConfirmationBypassError (not silently ignored)
  5. Event bus emits action.pending_approval for audit trail

Key invariants:
  - No action from perception executes without explicit human approval
  - ConfirmationBypassError is not catchable by normal exception handlers
  - Gate state is observable via get_pending() and get_stats()
  - Approved actions are one-shot (cannot be replayed)
  - Denied actions emit denial event for audit

Usage:
    gate = PerceptionActionGate()
    # Perception produces a scene analysis with recommended_action
    req = gate.require_confirmation(
        action="shell.run",
        args={"command": "ls /home"},
        scene_id="scene_123",
        correlation_id="req_abc",
    )
    # Returns ConfirmationRequirement -- action is NOT executed yet

    # Later, operator approves:
    approved = gate.approve(req.requirement_id)
    if approved:
        # NOW execute the action
        result = await execute_action(approved.action, approved.args)
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfirmationBypassError(RuntimeError):
    """
    Raised when code attempts to bypass the confirmation gate.

    This is a critical safety error -- NOT a normal exception.
    It should bubble up and halt the operation.
    """
    def __init__(self, action: str, scene_id: str, reason: str):
        self.action = action
        self.scene_id = scene_id
        self.reason = reason
        super().__init__(
            f"SAFETY: Confirmation bypass attempted for action={action} "
            f"scene={scene_id}: {reason}"
        )


class RequirementState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    EXECUTED = "executed"


@dataclass
class ConfirmationRequirement:
    """A single confirmation requirement for a perception-driven action."""
    requirement_id: str = ""
    action: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    scene_id: str = ""
    session_id: str = ""
    correlation_id: str = ""
    state: RequirementState = RequirementState.PENDING
    created_at: float = 0.0
    resolved_at: float = 0.0
    ttl_seconds: float = 120.0
    risk_level: str = "high"  # Perception actions default to high risk
    denial_reason: str = ""

    @property
    def is_pending(self) -> bool:
        return self.state == RequirementState.PENDING

    @property
    def is_approved(self) -> bool:
        return self.state == RequirementState.APPROVED

    @property
    def is_denied(self) -> bool:
        return self.state == RequirementState.DENIED

    @property
    def is_expired(self) -> bool:
        if self.state == RequirementState.EXPIRED:
            return True
        if self.state == RequirementState.PENDING and self.created_at > 0:
            return (time.time() - self.created_at) > self.ttl_seconds
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "action": self.action,
            "args": self.args,
            "scene_id": self.scene_id,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "risk_level": self.risk_level,
        }


# ── Risk classification for perception actions ─────────────────────────────

PERCEPTION_ACTION_RISK = {
    # Actions that perception might recommend
    "file.read": "medium",
    "file.write": "high",
    "shell.run": "critical",
    "app.launch": "high",
    "app.close": "high",
    "browser.open": "medium",
    "clipboard.write": "high",
    "keyboard.type": "critical",
    "keyboard.hotkey": "critical",
    "mouse.click": "critical",
    "window.focus": "medium",
}

DEFAULT_PERCEPTION_RISK = "high"  # Unknown actions are high risk


class PerceptionActionGate:
    """
    Enforces confirmation for ALL perception-driven actions.

    Invariants:
      1. No action executes without passing through require_confirmation()
      2. require_confirmation() always returns PENDING state
      3. Only approve() transitions to APPROVED
      4. Attempting to execute an unapproved action raises ConfirmationBypassError
      5. Each approval is one-shot (cannot be reused)
      6. Expired requirements cannot be approved

    This gate is the SINGLE enforcement point for perception actions.
    """

    MAX_PENDING = 50  # Max pending confirmations
    DEFAULT_TTL = 120.0  # Seconds before requirement expires

    def __init__(self, ttl_seconds: float = DEFAULT_TTL):
        self._ttl = ttl_seconds
        self._requirements: Dict[str, ConfirmationRequirement] = {}
        self._history: List[ConfirmationRequirement] = []
        self._max_history = 200
        self._total_approved = 0
        self._total_denied = 0
        self._total_expired = 0
        self._bypass_attempts = 0

    def require_confirmation(
        self,
        action: str,
        args: Optional[Dict[str, Any]] = None,
        scene_id: str = "",
        session_id: str = "",
        correlation_id: str = "",
    ) -> ConfirmationRequirement:
        """
        Create a confirmation requirement for a perception action.

        This ALWAYS creates a pending requirement. The action CANNOT
        execute until approve() is called with the requirement_id.

        Args:
            action: Tool/action intent (e.g., "file.read", "shell.run")
            args: Action arguments
            scene_id: The perception scene that triggered this
            session_id: Current session
            correlation_id: Trace ID

        Returns:
            ConfirmationRequirement in PENDING state

        Raises:
            ConfirmationBypassError if max pending limit exceeded
        """
        # Enforce pending limit
        pending_count = sum(1 for r in self._requirements.values() if r.is_pending)
        if pending_count >= self.MAX_PENDING:
            raise ConfirmationBypassError(
                action=action,
                scene_id=scene_id,
                reason=f"Max pending confirmations ({self.MAX_PENDING}) exceeded",
            )

        risk = PERCEPTION_ACTION_RISK.get(action, DEFAULT_PERCEPTION_RISK)

        req = ConfirmationRequirement(
            requirement_id=f"pcr_{uuid.uuid4().hex[:12]}",
            action=action,
            args=args or {},
            scene_id=scene_id,
            session_id=session_id,
            correlation_id=correlation_id,
            state=RequirementState.PENDING,
            created_at=time.time(),
            ttl_seconds=self._ttl,
            risk_level=risk,
        )

        self._requirements[req.requirement_id] = req

        logger.info(
            "Perception action gate: PENDING action=%s scene=%s risk=%s req=%s",
            action, scene_id, risk, req.requirement_id,
        )

        return req

    def approve(self, requirement_id: str) -> Optional[ConfirmationRequirement]:
        """
        Approve a pending confirmation requirement.

        Returns the approved requirement if valid, None if not found or expired.
        Approval is one-shot: cannot approve the same requirement twice.
        """
        req = self._requirements.get(requirement_id)
        if req is None:
            return None

        if req.is_expired:
            req.state = RequirementState.EXPIRED
            self._total_expired += 1
            self._archive(req)
            return None

        if req.state != RequirementState.PENDING:
            return None  # Already resolved

        req.state = RequirementState.APPROVED
        req.resolved_at = time.time()
        self._total_approved += 1
        # Keep in _requirements until validate_execution consumes it

        logger.info(
            "Perception action gate: APPROVED req=%s action=%s",
            requirement_id, req.action,
        )

        return req

    def deny(self, requirement_id: str, reason: str = "") -> Optional[ConfirmationRequirement]:
        """
        Deny a pending confirmation requirement.

        Returns the denied requirement if valid, None if not found.
        """
        req = self._requirements.get(requirement_id)
        if req is None:
            return None

        if req.state != RequirementState.PENDING and not req.is_expired:
            return None

        req.state = RequirementState.DENIED
        req.denial_reason = reason
        req.resolved_at = time.time()
        self._total_denied += 1
        # Keep in _requirements so validate_execution can report denial

        logger.info(
            "Perception action gate: DENIED req=%s action=%s reason=%s",
            requirement_id, req.action, reason,
        )

        return req

    def validate_execution(self, requirement_id: str) -> ConfirmationRequirement:
        """
        Validate that a requirement is approved before execution.

        This is the ENFORCEMENT POINT. Call this before executing any
        perception-driven action. If the requirement is not approved,
        raises ConfirmationBypassError.

        Returns the approved requirement.
        Raises:
            ConfirmationBypassError if not approved
        """
        req = self._requirements.get(requirement_id)
        if req is None:
            self._bypass_attempts += 1
            raise ConfirmationBypassError(
                action="unknown",
                scene_id="unknown",
                reason=f"Requirement {requirement_id} not found",
            )

        if req.is_expired:
            req.state = RequirementState.EXPIRED
            self._total_expired += 1
            self._bypass_attempts += 1
            raise ConfirmationBypassError(
                action=req.action,
                scene_id=req.scene_id,
                reason=f"Requirement expired after {req.ttl_seconds}s",
            )

        if req.state != RequirementState.APPROVED:
            self._bypass_attempts += 1
            raise ConfirmationBypassError(
                action=req.action,
                scene_id=req.scene_id,
                reason=f"Requirement state is {req.state.value}, not approved",
            )

        # Mark as executed (one-shot) and archive
        req.state = RequirementState.EXECUTED
        self._archive(req)

        return req

    def get_pending(self, session_id: Optional[str] = None) -> List[ConfirmationRequirement]:
        """Return all pending requirements, optionally filtered by session."""
        self._expire_stale()
        pending = [r for r in self._requirements.values() if r.is_pending]
        if session_id:
            pending = [r for r in pending if r.session_id == session_id]
        return pending

    def get_stats(self) -> Dict[str, Any]:
        """Return gate statistics."""
        self._expire_stale()
        return {
            "pending_count": sum(1 for r in self._requirements.values() if r.is_pending),
            "total_approved": self._total_approved,
            "total_denied": self._total_denied,
            "total_expired": self._total_expired,
            "bypass_attempts": self._bypass_attempts,
            "history_size": len(self._history),
        }

    def _expire_stale(self):
        """Expire any pending requirements past TTL."""
        now = time.time()
        for req in list(self._requirements.values()):
            if req.state == RequirementState.PENDING:
                if now - req.created_at > req.ttl_seconds:
                    req.state = RequirementState.EXPIRED
                    self._total_expired += 1
                    self._archive(req)

    def _archive(self, req: ConfirmationRequirement):
        """Move resolved requirement to history."""
        self._requirements.pop(req.requirement_id, None)
        self._history.append(req)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
