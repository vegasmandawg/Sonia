"""
OpenClaw — Action Safety Policy Engine

Classifies every inbound action request into one of three verdicts:

    ALLOW   — execute immediately, no user prompt required.
    CONFIRM — pause execution and require an explicit user approval
              token before proceeding.  Token has short TTL and is
              single-use.
    DENY    — refuse unconditionally.  Log and return a structured
              denial.

Rules are evaluated top-to-bottom; first match wins.  If no rule
matches, the default verdict (configurable, defaults to CONFIRM)
applies — safe-by-default.

Every decision is recorded with trace_id, matched rule, action,
and verdict so the audit trail is complete.

Usage:
    engine = PolicyEngine(rules=load_rules_from_config())
    decision = engine.evaluate(
        action="shell.run",
        args={"command": "Get-ChildItem"},
        context={"mode": "conversation", "user_id": "u1"},
        trace_id="t-001",
    )
    if decision.verdict == ActionVerdict.ALLOW:
        # proceed
    elif decision.verdict == ActionVerdict.CONFIRM:
        # request approval token from user
    else:
        # deny
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Verdict Enum
# ═══════════════════════════════════════════════════════════════════

class ActionVerdict(str, Enum):
    """Three-tier safety verdict for every action."""
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


# ═══════════════════════════════════════════════════════════════════
# Policy Rule
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PolicyRule:
    """
    A single policy rule.

    Fields:
        name:           Human-readable rule identifier.
        verdict:        The verdict when this rule matches.
        action_pattern: Regex that is matched against the action name
                        (e.g. "shell\\.run", "file\\..*", ".*").
        arg_patterns:   Optional dict of arg-key → regex.  ALL listed
                        patterns must match for the rule to fire.
        mode_filter:    Optional set of operational modes where this
                        rule is active.  Empty = all modes.
        description:    Why this rule exists (for audit / display).
        priority:       Lower numbers are evaluated first.  Rules with
                        equal priority keep insertion order.
    """

    name: str
    verdict: ActionVerdict
    action_pattern: str = ".*"
    arg_patterns: Dict[str, str] = field(default_factory=dict)
    mode_filter: Optional[set] = None
    description: str = ""
    priority: int = 100

    # ---- compiled regex (lazy) ------------------------------------------------

    _compiled_action: Optional[Pattern] = field(
        default=None, init=False, repr=False, compare=False,
    )
    _compiled_args: Optional[Dict[str, Pattern]] = field(
        default=None, init=False, repr=False, compare=False,
    )

    def _ensure_compiled(self) -> None:
        if self._compiled_action is None:
            self._compiled_action = re.compile(self.action_pattern, re.IGNORECASE)
        if self._compiled_args is None:
            self._compiled_args = {
                k: re.compile(v, re.IGNORECASE)
                for k, v in self.arg_patterns.items()
            }

    # ---- matching -------------------------------------------------------------

    def matches(
        self,
        action: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> bool:
        """
        Return True if this rule matches the given action + args + context.
        """
        self._ensure_compiled()

        # Action name must match
        if not self._compiled_action.fullmatch(action):  # type: ignore[union-attr]
            return False

        # All arg patterns must match
        for key, pattern in (self._compiled_args or {}).items():
            arg_val = str(args.get(key, ""))
            if not pattern.search(arg_val):
                return False

        # Mode filter (if set)
        if self.mode_filter:
            current_mode = context.get("mode", "")
            if current_mode not in self.mode_filter:
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialise rule for config / audit output."""
        return {
            "name": self.name,
            "verdict": self.verdict.value,
            "action_pattern": self.action_pattern,
            "arg_patterns": self.arg_patterns,
            "mode_filter": sorted(self.mode_filter) if self.mode_filter else None,
            "description": self.description,
            "priority": self.priority,
        }


# ═══════════════════════════════════════════════════════════════════
# Policy Decision (result of evaluation)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class PolicyDecision:
    """Result of a policy evaluation — immutable after creation."""

    verdict: ActionVerdict
    action: str
    rule_name: str          # name of the matched rule ("__default__" if none)
    trace_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""
    args_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "action": self.action,
            "rule_name": self.rule_name,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "args_summary": self.args_summary,
        }


# ═══════════════════════════════════════════════════════════════════
# Policy Engine
# ═══════════════════════════════════════════════════════════════════

class PolicyEngine:
    """
    Stateless rule evaluator.

    Holds an ordered list of PolicyRule objects.  On each ``evaluate()``
    call the rules are tried top-to-bottom (lowest priority number
    first); first match wins.  If nothing matches, the configurable
    ``default_verdict`` applies (defaults to CONFIRM — safe by
    default).

    All decisions are appended to an internal audit log that can be
    queried or drained.
    """

    def __init__(
        self,
        rules: Optional[List[PolicyRule]] = None,
        default_verdict: ActionVerdict = ActionVerdict.CONFIRM,
    ):
        self._rules: List[PolicyRule] = []
        self._default_verdict = default_verdict
        self._audit_log: List[Dict[str, Any]] = []

        if rules:
            for r in rules:
                self.add_rule(r)

    # ---- rule management ------------------------------------------------------

    @property
    def rules(self) -> List[PolicyRule]:
        """Return a copy of the current rule list (sorted by priority)."""
        return list(self._rules)

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def add_rule(self, rule: PolicyRule) -> None:
        """Insert a rule and re-sort by priority (stable sort)."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name.  Returns True if found."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def clear_rules(self) -> None:
        self._rules.clear()

    # ---- evaluation -----------------------------------------------------------

    def evaluate(
        self,
        action: str,
        args: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> PolicyDecision:
        """
        Evaluate *action* against the rule set.

        Args:
            action:   Tool / action name (e.g. "shell.run").
            args:     Arguments dict (command, path, etc.).
            context:  Runtime context (mode, user_id, …).
            trace_id: Correlation / trace identifier.

        Returns:
            PolicyDecision with verdict, matched rule, and metadata.
        """
        args = args or {}
        context = context or {}

        # Summarise args for the audit record (truncate long values)
        args_summary = {
            k: (str(v)[:120] if len(str(v)) > 120 else v)
            for k, v in args.items()
        }

        for rule in self._rules:
            if rule.matches(action, args, context):
                decision = PolicyDecision(
                    verdict=rule.verdict,
                    action=action,
                    rule_name=rule.name,
                    trace_id=trace_id,
                    reason=rule.description or f"Matched rule '{rule.name}'",
                    args_summary=args_summary,
                )
                self._record(decision)
                return decision

        # No rule matched → default verdict
        decision = PolicyDecision(
            verdict=self._default_verdict,
            action=action,
            rule_name="__default__",
            trace_id=trace_id,
            reason=f"No rule matched; default verdict = {self._default_verdict.value}",
            args_summary=args_summary,
        )
        self._record(decision)
        return decision

    # ---- audit log ------------------------------------------------------------

    def _record(self, decision: PolicyDecision) -> None:
        """Append decision to internal audit log and emit a log line."""
        entry = decision.to_dict()
        self._audit_log.append(entry)

        lvl = {
            ActionVerdict.ALLOW: logging.DEBUG,
            ActionVerdict.CONFIRM: logging.INFO,
            ActionVerdict.DENY: logging.WARNING,
        }.get(decision.verdict, logging.INFO)

        logger.log(
            lvl,
            "policy_decision  verdict=%s  action=%s  rule=%s  trace=%s",
            decision.verdict.value,
            decision.action,
            decision.rule_name,
            decision.trace_id,
        )

    @property
    def audit_log(self) -> List[Dict[str, Any]]:
        """Return a copy of the audit log."""
        return list(self._audit_log)

    @property
    def decision_count(self) -> int:
        return len(self._audit_log)

    def recent_decisions(self, n: int = 20) -> List[Dict[str, Any]]:
        """Return the last *n* decisions."""
        return self._audit_log[-n:]

    def clear_audit_log(self) -> None:
        self._audit_log.clear()

    # ---- serialisation --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise engine state for diagnostics."""
        return {
            "rule_count": self.rule_count,
            "default_verdict": self._default_verdict.value,
            "decision_count": self.decision_count,
            "rules": [r.to_dict() for r in self._rules],
        }


# ═══════════════════════════════════════════════════════════════════
# Built-in rule helpers
# ═══════════════════════════════════════════════════════════════════

def default_safety_rules() -> List[PolicyRule]:
    """
    Return the canonical set of safety rules for Sonia.

    Rule evaluation order (by priority):
        10  — hard deny (destructive commands, escape attempts)
        20  — readonly allow (reads, listings, health checks)
        50  — confirm (writes, process control, browser)
        90  — catch-all confirm (anything unknown)
    """
    rules: List[PolicyRule] = []

    # ── Priority 10: DENY — always blocked ─────────────────────────
    rules.append(PolicyRule(
        name="deny_destructive_shell",
        verdict=ActionVerdict.DENY,
        action_pattern=r"shell\.run",
        arg_patterns={
            "command": r"(?i)(Remove-Item|Delete|Clear-Content|Stop-Process|"
                       r"Stop-Service|Set-ExecutionPolicy|Invoke-Expression|"
                       r"IEX|rm\s|del\s|format\s)",
        },
        description="Block shell commands that delete, kill, or bypass policy",
        priority=10,
    ))

    rules.append(PolicyRule(
        name="deny_path_escape",
        verdict=ActionVerdict.DENY,
        action_pattern=r"file\..*",
        arg_patterns={
            "path": r"(?i)(C:\\|D:\\|\\\\|%|\.\.[\\/])",
        },
        description="Block file operations outside the S:\\ sandbox",
        priority=10,
    ))

    rules.append(PolicyRule(
        name="deny_unknown_destructive",
        verdict=ActionVerdict.DENY,
        action_pattern=r".*\.delete$|.*\.destroy$|.*\.drop$",
        description="Block any action whose name ends with delete/destroy/drop",
        priority=10,
    ))

    # ── Priority 20: ALLOW — safe read-only operations ─────────────
    rules.append(PolicyRule(
        name="allow_file_read",
        verdict=ActionVerdict.ALLOW,
        action_pattern=r"file\.read",
        description="File reads within sandbox are always allowed",
        priority=20,
    ))

    rules.append(PolicyRule(
        name="allow_readonly_shell",
        verdict=ActionVerdict.ALLOW,
        action_pattern=r"shell\.run",
        arg_patterns={
            "command": r"(?i)^(Get-ChildItem|Get-Item|Get-Content|"
                       r"Test-Path|Resolve-Path|Get-Location|"
                       r"Get-Process|Get-Service|\$PSVersionTable)(\s|$)",
        },
        description="Allow read-only shell commands from the allowlist",
        priority=20,
    ))

    rules.append(PolicyRule(
        name="allow_health_check",
        verdict=ActionVerdict.ALLOW,
        action_pattern=r"health\.check|healthz",
        description="Health checks are always allowed",
        priority=20,
    ))

    # ── Priority 50: CONFIRM — actions that modify state ───────────
    rules.append(PolicyRule(
        name="confirm_file_write",
        verdict=ActionVerdict.CONFIRM,
        action_pattern=r"file\.write",
        description="File writes require user confirmation",
        priority=50,
    ))

    rules.append(PolicyRule(
        name="confirm_shell_write",
        verdict=ActionVerdict.CONFIRM,
        action_pattern=r"shell\.run",
        description="Non-readonly shell commands require confirmation",
        priority=50,
    ))

    rules.append(PolicyRule(
        name="confirm_browser_open",
        verdict=ActionVerdict.CONFIRM,
        action_pattern=r"browser\.open",
        description="Opening URLs requires confirmation",
        priority=50,
    ))

    rules.append(PolicyRule(
        name="confirm_process_control",
        verdict=ActionVerdict.CONFIRM,
        action_pattern=r"process\.(start|stop|kill)",
        description="Process control requires confirmation",
        priority=50,
    ))

    # ── Priority 90: catch-all ─────────────────────────────────────
    rules.append(PolicyRule(
        name="confirm_unknown",
        verdict=ActionVerdict.CONFIRM,
        action_pattern=r".*",
        description="Unknown actions default to confirm",
        priority=90,
    ))

    return rules
