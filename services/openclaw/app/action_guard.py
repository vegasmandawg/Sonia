"""
OpenClaw -- Action Guard (Pre-Execution Wrapper)

The single choke-point that every action request must pass through
before reaching the executor registry.  Wires together:

    PolicyEngine   -> classify action as allow / confirm / deny
    ConfirmationManager -> manage approval tokens for CONFIRM verdicts

Flow:
    1.  ``guard(action, args, context, trace_id)`` is called.
    2.  Policy engine evaluates the action.
    3.  If ALLOW  -> return GuardResult(proceed=True).
    4.  If DENY   -> return GuardResult(proceed=False, denied=True).
    5.  If CONFIRM ->
        a.  If a valid approval_token is provided in context,
            redeem it.  On success -> proceed=True.
        b.  Otherwise, mint a new confirmation token and return
            GuardResult(proceed=False, needs_confirmation=True,
            confirmation_token=...).

Every decision is logged with full trace_id, policy rule, and
action metadata.

Usage:
    guard = ActionGuard(engine, confirmations)
    result = guard.guard(
        action="file.write",
        args={"path": "S:\\\\tmp\\\\x"},
        context={"mode": "conversation"},
        trace_id="t-001",
    )
    if result.proceed:
        # execute action
    elif result.needs_confirmation:
        # present result.confirmation_token to user
    else:
        # denied
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.policy_engine import ActionVerdict, PolicyDecision, PolicyEngine
from app.confirmations import (
    ConfirmationManager,
    ConfirmationToken,
    RedeemResult,
    TokenState,
)

logger = logging.getLogger(__name__)


# ===================================================================
# Guard Result
# ===================================================================

@dataclass
class GuardResult:
    """
    Outcome of an action guard evaluation.

    Fields:
        proceed:             True if the action may execute now.
        denied:              True if the action was unconditionally denied.
        needs_confirmation:  True if user approval is required.
        confirmation_token:  The minted token (only when needs_confirmation).
        policy_decision:     The underlying PolicyDecision.
        redeem_result:       If a token was redeemed, the result.
        trace_id:            Correlation ID.
        reason:              Human-readable explanation.
    """

    proceed: bool = False
    denied: bool = False
    needs_confirmation: bool = False
    confirmation_token: Optional[ConfirmationToken] = None
    policy_decision: Optional[PolicyDecision] = None
    redeem_result: Optional[RedeemResult] = None
    trace_id: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "proceed": self.proceed,
            "denied": self.denied,
            "needs_confirmation": self.needs_confirmation,
            "trace_id": self.trace_id,
            "reason": self.reason,
        }
        if self.policy_decision:
            d["policy_decision"] = self.policy_decision.to_dict()
        if self.confirmation_token:
            d["confirmation_token"] = self.confirmation_token.to_dict()
        if self.redeem_result:
            d["redeem_result"] = self.redeem_result.to_dict()
        return d


# ===================================================================
# Action Guard
# ===================================================================

class ActionGuard:
    """
    Pre-execution guard that enforces the action safety policy.

    Instantiate with a PolicyEngine and ConfirmationManager, then
    call ``guard()`` for every inbound action request.
    """

    def __init__(
        self,
        engine: PolicyEngine,
        confirmations: ConfirmationManager,
    ):
        self._engine = engine
        self._confirmations = confirmations
        self._guard_log: List[Dict[str, Any]] = []

    # ── main entry point ───────────────────────────────────────────

    def guard(
        self,
        action: str,
        args: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> GuardResult:
        """
        Evaluate an action request and return whether it may proceed.

        If the caller already has an approval token (from a previous
        CONFIRM round-trip), pass it in ``context["approval_token"]``.

        Args:
            action:   Action / tool name.
            args:     Action arguments.
            context:  Runtime context (mode, user_id, approval_token).
            trace_id: Correlation ID.

        Returns:
            GuardResult indicating proceed, deny, or needs_confirmation.
        """
        args = args or {}
        context = context or {}

        # Step 1: evaluate policy
        decision = self._engine.evaluate(
            action=action,
            args=args,
            context=context,
            trace_id=trace_id,
        )

        # Step 2: act on verdict
        if decision.verdict == ActionVerdict.ALLOW:
            result = self._handle_allow(decision, trace_id)
        elif decision.verdict == ActionVerdict.DENY:
            result = self._handle_deny(decision, trace_id)
        else:  # CONFIRM
            result = self._handle_confirm(
                decision, action, args, context, trace_id,
            )

        self._record(result)
        return result

    # ── deny a pending token explicitly ────────────────────────────

    def deny_pending(
        self,
        token_id: str,
        trace_id: str = "",
        reason: str = "User denied",
    ) -> RedeemResult:
        """
        Explicitly deny a pending confirmation token.
        """
        result = self._confirmations.deny_token(
            token_id, trace_id, reason=reason,
        )
        self._record_event("deny_pending", token_id, trace_id,
                           accepted=False, reason=reason)
        return result

    # ── handler internals ──────────────────────────────────────────

    def _handle_allow(
        self,
        decision: PolicyDecision,
        trace_id: str,
    ) -> GuardResult:
        logger.debug(
            "guard: ALLOW  action=%s  rule=%s  trace=%s",
            decision.action, decision.rule_name, trace_id,
        )
        return GuardResult(
            proceed=True,
            policy_decision=decision,
            trace_id=trace_id,
            reason=f"Allowed by rule '{decision.rule_name}'",
        )

    def _handle_deny(
        self,
        decision: PolicyDecision,
        trace_id: str,
    ) -> GuardResult:
        logger.warning(
            "guard: DENY  action=%s  rule=%s  trace=%s",
            decision.action, decision.rule_name, trace_id,
        )
        return GuardResult(
            denied=True,
            policy_decision=decision,
            trace_id=trace_id,
            reason=decision.reason,
        )

    def _handle_confirm(
        self,
        decision: PolicyDecision,
        action: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
        trace_id: str,
    ) -> GuardResult:
        """
        Handle CONFIRM verdict: check for existing token or mint new one.
        """
        # Check if caller already has an approval token
        approval_token_id = context.get("approval_token")

        if approval_token_id:
            # Attempt to redeem the token
            redeem = self._confirmations.redeem_token(
                approval_token_id, trace_id,
            )
            if redeem.accepted:
                logger.info(
                    "guard: CONFIRM -> APPROVED  action=%s  token=%s  trace=%s",
                    action, approval_token_id, trace_id,
                )
                return GuardResult(
                    proceed=True,
                    policy_decision=decision,
                    redeem_result=redeem,
                    trace_id=trace_id,
                    reason=f"Approved via token {approval_token_id}",
                )
            else:
                logger.warning(
                    "guard: CONFIRM -> TOKEN_REJECTED  action=%s  "
                    "token=%s  reason=%s  trace=%s",
                    action, approval_token_id, redeem.reason, trace_id,
                )
                return GuardResult(
                    denied=True,
                    policy_decision=decision,
                    redeem_result=redeem,
                    trace_id=trace_id,
                    reason=f"Token rejected: {redeem.reason}",
                )

        # No approval token provided -> mint a new one
        token = self._confirmations.mint_token(
            action=action,
            args=args,
            trace_id=trace_id,
        )
        logger.info(
            "guard: CONFIRM -> NEEDS_APPROVAL  action=%s  "
            "token=%s  trace=%s",
            action, token.token_id, trace_id,
        )
        return GuardResult(
            needs_confirmation=True,
            confirmation_token=token,
            policy_decision=decision,
            trace_id=trace_id,
            reason=f"Confirmation required: {decision.reason}",
        )

    # ── audit log ──────────────────────────────────────────────────

    def _record(self, result: GuardResult) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "proceed": result.proceed,
            "denied": result.denied,
            "needs_confirmation": result.needs_confirmation,
            "trace_id": result.trace_id,
            "reason": result.reason,
        }
        if result.policy_decision:
            entry["verdict"] = result.policy_decision.verdict.value
            entry["action"] = result.policy_decision.action
            entry["rule"] = result.policy_decision.rule_name
        self._guard_log.append(entry)

    def _record_event(self, event: str, token_id: str,
                      trace_id: str, **kwargs: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "token_id": token_id,
            "trace_id": trace_id,
        }
        entry.update(kwargs)
        self._guard_log.append(entry)

    @property
    def guard_log(self) -> List[Dict[str, Any]]:
        return list(self._guard_log)

    def recent_guard_log(self, n: int = 20) -> List[Dict[str, Any]]:
        return self._guard_log[-n:]

    @property
    def guard_count(self) -> int:
        return len(self._guard_log)

    # ── diagnostics ────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guard_count": self.guard_count,
            "policy_engine": self._engine.to_dict(),
            "confirmations": self._confirmations.to_dict(),
        }
