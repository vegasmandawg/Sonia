"""
OpenClaw App -- Action Safety Layer

Provides mandatory confirmation policy for high-impact operations.
Every action is classified as allow / confirm / deny before execution.
"""

from app.policy_engine import (
    ActionVerdict,
    PolicyDecision,
    PolicyRule,
    PolicyEngine,
    default_safety_rules,
)

from app.confirmations import (
    TokenState,
    ConfirmationToken,
    RedeemResult,
    ConfirmationManager,
)

from app.action_guard import (
    GuardResult,
    ActionGuard,
)

__all__ = [
    # Policy engine
    "ActionVerdict",
    "PolicyDecision",
    "PolicyRule",
    "PolicyEngine",
    "default_safety_rules",
    # Confirmation tokens
    "TokenState",
    "ConfirmationToken",
    "RedeemResult",
    "ConfirmationManager",
    # Action guard
    "GuardResult",
    "ActionGuard",
]
