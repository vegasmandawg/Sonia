"""
EVA-OS -- SafeOrchestrator

Wraps the existing EVAOSOrchestrator.validate_and_gate_tool_call()
with the OpenClaw ActionGuard so that every tool call is evaluated
against the three-tier safety policy (allow / confirm / deny) before
reaching the executor.

Integration points:
    - Receives tool call requests from eva_os main.py endpoints.
    - Delegates policy + confirmation logic to ActionGuard.
    - Returns structured results compatible with existing API contracts.
    - Enriches /healthz with safety layer diagnostics.

Usage:
    orch = SafeOrchestrator()
    result = orch.gate_tool_call(tool_call_dict, context, trace_id)
    if result["status"] == "approved":
        # proceed to OpenClaw /execute
    elif result["status"] == "approval_required":
        # present confirmation to user
    else:
        # denied
"""

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ===================================================================
# Import OpenClaw safety modules
# ===================================================================

_OPENCLAW_ROOT = str(
    Path(__file__).resolve().parent.parent.parent / "openclaw"
)


def _ensure_openclaw_imports():
    """
    Ensure openclaw's app modules are importable.

    Strategy: temporarily clear any cached 'app' module, insert
    openclaw root at the front of sys.path, import what we need,
    then restore state.
    """
    # Save and temporarily remove any cached 'app' module
    saved_app = sys.modules.pop("app", None)
    saved_pe = sys.modules.pop("app.policy_engine", None)
    saved_cf = sys.modules.pop("app.confirmations", None)
    saved_ag = sys.modules.pop("app.action_guard", None)

    # Add openclaw root to front of path
    had_path = _OPENCLAW_ROOT in sys.path
    if not had_path:
        sys.path.insert(0, _OPENCLAW_ROOT)

    try:
        import app.policy_engine as pe
        import app.confirmations as cf
        import app.action_guard as ag

        return {
            "ActionVerdict": pe.ActionVerdict,
            "PolicyEngine": pe.PolicyEngine,
            "PolicyRule": pe.PolicyRule,
            "default_safety_rules": pe.default_safety_rules,
            "ConfirmationManager": cf.ConfirmationManager,
            "ActionGuard": ag.ActionGuard,
            "GuardResult": ag.GuardResult,
        }
    finally:
        # Restore the original 'app' module if there was one
        if saved_app is not None:
            sys.modules["app"] = saved_app
        if saved_pe is not None:
            sys.modules["app.policy_engine"] = saved_pe
        if saved_cf is not None:
            sys.modules["app.confirmations"] = saved_cf
        if saved_ag is not None:
            sys.modules["app.action_guard"] = saved_ag

        # Keep openclaw on sys.path (at the end) for runtime use
        if not had_path:
            sys.path.remove(_OPENCLAW_ROOT)
            sys.path.append(_OPENCLAW_ROOT)


_oc = _ensure_openclaw_imports()
ActionVerdict = _oc["ActionVerdict"]
PolicyEngine = _oc["PolicyEngine"]
PolicyRule = _oc["PolicyRule"]
default_safety_rules = _oc["default_safety_rules"]
ConfirmationManager = _oc["ConfirmationManager"]
ActionGuard = _oc["ActionGuard"]
GuardResult = _oc["GuardResult"]


# ===================================================================
# Config loading
# ===================================================================

_DEFAULT_CONFIG_PATH = r"S:\config\sonia-config.json"


def _load_safety_config(config_path: str = _DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Load the action_safety section from sonia-config.json.
    Returns an empty dict if missing.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("action_safety", {})
    except Exception as e:
        logger.warning("orchestrator: cannot load safety config: %s", e)
        return {}


# ===================================================================
# SafeOrchestrator
# ===================================================================

class SafeOrchestrator:
    """
    Drop-in wrapper that adds the ActionGuard to EVA-OS orchestration.
    """

    def __init__(self, config_path: str = _DEFAULT_CONFIG_PATH):
        safety_cfg = _load_safety_config(config_path)

        ttl = safety_cfg.get("confirmation_ttl_seconds", 120.0)
        max_pending = safety_cfg.get("max_pending_confirmations", 50)
        default_verdict_str = safety_cfg.get("default_verdict", "confirm")

        default_verdict = {
            "allow": ActionVerdict.ALLOW,
            "confirm": ActionVerdict.CONFIRM,
            "deny": ActionVerdict.DENY,
        }.get(default_verdict_str.lower(), ActionVerdict.CONFIRM)

        self._engine = PolicyEngine(
            rules=default_safety_rules(),
            default_verdict=default_verdict,
        )

        custom_rules = safety_cfg.get("custom_rules", [])
        for rule_dict in custom_rules:
            try:
                rule = PolicyRule(
                    name=rule_dict["name"],
                    verdict=ActionVerdict(rule_dict["verdict"]),
                    action_pattern=rule_dict.get("action_pattern", ".*"),
                    arg_patterns=rule_dict.get("arg_patterns", {}),
                    description=rule_dict.get("description", ""),
                    priority=rule_dict.get("priority", 100),
                )
                self._engine.add_rule(rule)
            except Exception as e:
                logger.warning("orchestrator: bad custom rule %s: %s",
                               rule_dict.get("name", "?"), e)

        self._confirmations = ConfirmationManager(
            ttl_seconds=ttl,
            max_pending=max_pending,
        )

        self._guard = ActionGuard(self._engine, self._confirmations)

        logger.info(
            "SafeOrchestrator: initialized  rules=%d  ttl=%.0fs  "
            "max_pending=%d  default=%s",
            self._engine.rule_count, ttl, max_pending,
            default_verdict.value,
        )

    # ── main gate ──────────────────────────────────────────────────

    def gate_tool_call(
        self,
        tool_call: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        action = tool_call.get("tool_name", "")
        args = tool_call.get("args", {})
        ctx = dict(context or {})

        if "approval_token" in tool_call and "approval_token" not in ctx:
            ctx["approval_token"] = tool_call["approval_token"]

        result = self._guard.guard(
            action=action, args=args, context=ctx, trace_id=trace_id,
        )
        return self._format_result(result, tool_call)

    # ── explicit deny ──────────────────────────────────────────────

    def deny_pending_approval(
        self, token_id: str, trace_id: str = "",
        reason: str = "User denied",
    ) -> Dict[str, Any]:
        redeem = self._guard.deny_pending(token_id, trace_id, reason)
        return {
            "status": "denied",
            "token_id": token_id,
            "reason": reason,
            "accepted": redeem.accepted,
        }

    # ── queries ────────────────────────────────────────────────────

    def pending_approvals(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._confirmations.pending_tokens()]

    # ── diagnostics ────────────────────────────────────────────────

    def safety_status(self) -> Dict[str, Any]:
        return {
            "policy_rules": self._engine.rule_count,
            "policy_decisions": self._engine.decision_count,
            "pending_confirmations": self._confirmations.pending_count,
            "total_tokens": self._confirmations.total_count,
            "guard_evaluations": self._guard.guard_count,
        }

    def to_dict(self) -> Dict[str, Any]:
        return self._guard.to_dict()

    # ── formatting ─────────────────────────────────────────────────

    @staticmethod
    def _format_result(result: GuardResult, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        tool_call_id = tool_call.get("id", "")

        if result.proceed:
            return {
                "status": "approved",
                "tool_call_id": tool_call_id,
                "trace_id": result.trace_id,
                "reason": result.reason,
            }

        if result.needs_confirmation:
            token = result.confirmation_token
            return {
                "status": "approval_required",
                "tool_call_id": tool_call_id,
                "trace_id": result.trace_id,
                "reason": result.reason,
                "approval_request": {
                    "token_id": token.token_id if token else "",
                    "action": token.action if token else "",
                    "summary": token.summary if token else "",
                    "ttl_seconds": token.ttl_seconds if token else 0,
                    "remaining_seconds": (
                        round(token.remaining_seconds, 1) if token else 0
                    ),
                },
            }

        return {
            "status": "denied",
            "tool_call_id": tool_call_id,
            "trace_id": result.trace_id,
            "reason": result.reason,
        }
