"""
SONIA Policy Engine (v1.0)

Hot-reloadable YAML-based tool authorization policy.
Evaluates tool execution requests against policy rules.

Usage:
    engine = PolicyEngine()
    verdict = engine.evaluate("filesystem.read_file", user_id="user_001")
    # verdict.action = "allow" | "deny" | "confirm"
    # verdict.reason = "..."
    # verdict.rule_name = "allow_file_read"

Policy files are loaded from S:\\config\\policies\\*.yaml
Changes are detected on each evaluate() call (stat-based, <1ms overhead).
"""

import fnmatch
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("api-gateway.policy")

POLICY_DIR = Path(r"S:\config\policies")
RELOAD_CHECK_INTERVAL = 5.0  # seconds between mtime checks


@dataclass
class PolicyRule:
    """A single policy rule."""
    name: str
    tool_pattern: str
    action: str  # "allow", "deny", "confirm"
    reason: str = ""
    conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyVerdict:
    """Result of evaluating a tool request against policy."""
    action: str  # "allow", "deny", "confirm"
    reason: str
    rule_name: str = ""
    rate_limited: bool = False


@dataclass
class PolicyConfig:
    """Parsed policy configuration."""
    version: str = "1.0"
    description: str = ""
    default_verdict: str = "confirm"
    default_reason: str = "No matching rule"
    rules: List[PolicyRule] = field(default_factory=list)
    loaded_at: float = 0.0
    source_file: str = ""
    file_mtime: float = 0.0


class PolicyEngine:
    """
    Evaluates tool execution requests against YAML policy rules.
    Supports hot-reload: policy files are re-read when their mtime changes.
    """

    def __init__(self, policy_dir: Optional[Path] = None):
        self._policy_dir = policy_dir or POLICY_DIR
        self._configs: List[PolicyConfig] = []
        self._last_check_time: float = 0.0
        self._mtimes: Dict[str, float] = {}
        self._rate_counts: Dict[str, List[float]] = {}  # rule_name -> list of timestamps
        self._load_policies()

    def evaluate(
        self,
        tool_name: str,
        user_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PolicyVerdict:
        """
        Evaluate a tool execution request against policy rules.

        Args:
            tool_name: The tool being invoked (e.g., "filesystem.read_file").
            user_id: The user making the request.
            metadata: Additional context for condition evaluation.

        Returns:
            PolicyVerdict with action, reason, and matched rule name.
        """
        # Hot-reload check
        now = time.monotonic()
        if now - self._last_check_time > RELOAD_CHECK_INTERVAL:
            self._check_and_reload()
            self._last_check_time = now

        # Evaluate rules in order across all loaded policy files
        for config in self._configs:
            for rule in config.rules:
                if self._matches(rule, tool_name, user_id, metadata):
                    # Check rate limit condition
                    if rule.conditions.get("max_per_minute"):
                        max_rpm = rule.conditions["max_per_minute"]
                        if self._is_rate_limited(rule.name, max_rpm):
                            return PolicyVerdict(
                                action="deny",
                                reason=f"Rate limited: {max_rpm}/min exceeded for {rule.name}",
                                rule_name=rule.name,
                                rate_limited=True,
                            )
                        self._record_rate(rule.name)

                    return PolicyVerdict(
                        action=rule.action,
                        reason=rule.reason,
                        rule_name=rule.name,
                    )

        # No rule matched -- use default from first loaded policy
        if self._configs:
            cfg = self._configs[0]
            return PolicyVerdict(
                action=cfg.default_verdict,
                reason=cfg.default_reason,
            )

        return PolicyVerdict(action="confirm", reason="No policy loaded")

    def get_stats(self) -> Dict[str, Any]:
        """Return policy engine statistics."""
        total_rules = sum(len(c.rules) for c in self._configs)
        return {
            "policy_files": len(self._configs),
            "total_rules": total_rules,
            "policy_dir": str(self._policy_dir),
            "last_reload": max((c.loaded_at for c in self._configs), default=0),
            "files": [
                {
                    "file": c.source_file,
                    "version": c.version,
                    "rules": len(c.rules),
                    "default_verdict": c.default_verdict,
                }
                for c in self._configs
            ],
        }

    def reload(self):
        """Force reload all policy files."""
        self._load_policies()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _matches(
        self,
        rule: PolicyRule,
        tool_name: str,
        user_id: str,
        metadata: Optional[Dict[str, Any]],
    ) -> bool:
        """Check if a rule matches the tool request."""
        # Pattern match on tool name
        if not fnmatch.fnmatch(tool_name, rule.tool_pattern):
            return False

        conditions = rule.conditions
        if not conditions:
            return True

        # user_ids condition
        if "user_ids" in conditions:
            allowed = conditions["user_ids"]
            if isinstance(allowed, list) and user_id not in allowed:
                return False

        # require_tag condition
        if "require_tag" in conditions:
            required_tag = conditions["require_tag"]
            tags = (metadata or {}).get("tags", [])
            if required_tag not in tags:
                return False

        return True

    def _is_rate_limited(self, rule_name: str, max_per_minute: int) -> bool:
        """Check if the rate limit for a rule has been exceeded."""
        now = time.time()
        window_start = now - 60.0

        timestamps = self._rate_counts.get(rule_name, [])
        # Clean old entries
        timestamps = [t for t in timestamps if t > window_start]
        self._rate_counts[rule_name] = timestamps

        return len(timestamps) >= max_per_minute

    def _record_rate(self, rule_name: str):
        """Record a rate event for a rule."""
        if rule_name not in self._rate_counts:
            self._rate_counts[rule_name] = []
        self._rate_counts[rule_name].append(time.time())

    def _load_policies(self):
        """Load all YAML policy files from the policy directory."""
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed -- policy engine disabled")
            return

        self._configs.clear()
        self._mtimes.clear()

        if not self._policy_dir.exists():
            logger.warning("Policy directory not found: %s", self._policy_dir)
            return

        yaml_files = sorted(self._policy_dir.glob("*.yaml")) + sorted(self._policy_dir.glob("*.yml"))

        for path in yaml_files:
            try:
                mtime = path.stat().st_mtime
                self._mtimes[str(path)] = mtime

                raw = path.read_text(encoding="utf-8")
                data = yaml.safe_load(raw)
                if not isinstance(data, dict):
                    continue

                config = PolicyConfig(
                    version=str(data.get("version", "1.0")),
                    description=data.get("description", ""),
                    default_verdict=data.get("default_verdict", "confirm"),
                    default_reason=data.get("default_reason", "No matching rule"),
                    loaded_at=time.time(),
                    source_file=path.name,
                    file_mtime=mtime,
                )

                for rule_data in data.get("rules", []):
                    if not isinstance(rule_data, dict):
                        continue
                    rule = PolicyRule(
                        name=rule_data.get("name", "unnamed"),
                        tool_pattern=rule_data.get("tool_pattern", ""),
                        action=rule_data.get("action", "confirm"),
                        reason=rule_data.get("reason", ""),
                        conditions=rule_data.get("conditions", {}),
                    )
                    config.rules.append(rule)

                self._configs.append(config)
                logger.info("Loaded policy: %s (%d rules)", path.name, len(config.rules))

            except Exception as e:
                logger.error("Failed to load policy %s: %s", path, e)

    def _check_and_reload(self):
        """Check if any policy files have changed and reload if needed."""
        if not self._policy_dir.exists():
            return

        needs_reload = False
        current_files = set()

        for path in list(self._policy_dir.glob("*.yaml")) + list(self._policy_dir.glob("*.yml")):
            current_files.add(str(path))
            try:
                mtime = path.stat().st_mtime
                old_mtime = self._mtimes.get(str(path), 0)
                if mtime != old_mtime:
                    needs_reload = True
                    logger.info("Policy file changed: %s", path.name)
            except OSError:
                pass

        # Check for deleted files
        if set(self._mtimes.keys()) != current_files:
            needs_reload = True

        if needs_reload:
            logger.info("Reloading policies...")
            self._load_policies()


# Global instance
_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    """Get or create the global policy engine."""
    global _engine
    if _engine is None:
        _engine = PolicyEngine()
    return _engine
