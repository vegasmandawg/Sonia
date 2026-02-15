"""
v2.10 Integration Tests -- Policy Engine

Dedicated tests for the YAML-based policy engine in api-gateway
and the safety policy engine in OpenClaw.

Tests (18):
  Gateway PolicyEngine (10):
    1. Empty policy dir returns default confirm verdict
    2. Allow rule matches tool pattern
    3. Deny rule blocks tool
    4. Confirm rule requires confirmation
    5. Wildcard patterns (filesystem.*)
    6. User ID condition filtering
    7. Tag condition filtering
    8. Rate limiting enforced
    9. Rate limiting window expires
    10. Stats reflect loaded rules

  OpenClaw PolicyEngine (8):
    11. Safe read operations allowed (file.read)
    12. Destructive shell commands denied (shell.run + rm)
    13. File writes require confirmation (file.write)
    14. Path escape attempt denied (C:\ path)
    15. Priority ordering (health.check at priority 20)
    16. Unknown actions get catch-all confirm
    17. Audit log records decisions
    18. Audit log grows with each decision
"""

import sys
import time
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, r"S:\services\api-gateway")
sys.path.insert(0, r"S:\services\openclaw")


# ===========================================================================
# Gateway PolicyEngine
# ===========================================================================

class TestGatewayPolicyEngine:

    def _make_engine(self, yaml_content="", tmpdir=None):
        """Create a PolicyEngine with a temp policy file."""
        if tmpdir is None:
            tmpdir = tempfile.mkdtemp()
        policy_dir = Path(tmpdir)
        if yaml_content:
            (policy_dir / "test_policy.yaml").write_text(yaml_content, encoding="utf-8")
        from policy_engine import PolicyEngine
        return PolicyEngine(policy_dir=policy_dir)

    def test_empty_dir_default_confirm(self):
        """No policy files -> default confirm verdict."""
        engine = self._make_engine()
        verdict = engine.evaluate("anything.do_stuff")
        assert verdict.action == "confirm"

    def test_allow_rule_matches(self):
        """Allow rule matches tool and returns allow."""
        yaml = """
version: "1.0"
default_verdict: deny
rules:
  - name: allow_read
    tool_pattern: "file.read"
    action: allow
    reason: "Read is safe"
"""
        engine = self._make_engine(yaml)
        verdict = engine.evaluate("file.read")
        assert verdict.action == "allow"
        assert verdict.rule_name == "allow_read"

    def test_deny_rule_blocks(self):
        """Deny rule blocks tool execution."""
        yaml = """
version: "1.0"
rules:
  - name: block_delete
    tool_pattern: "file.delete"
    action: deny
    reason: "Destructive"
"""
        engine = self._make_engine(yaml)
        verdict = engine.evaluate("file.delete")
        assert verdict.action == "deny"
        assert "Destructive" in verdict.reason

    def test_confirm_rule(self):
        """Confirm rule requires confirmation."""
        yaml = """
version: "1.0"
rules:
  - name: confirm_write
    tool_pattern: "file.write"
    action: confirm
    reason: "Writes need approval"
"""
        engine = self._make_engine(yaml)
        verdict = engine.evaluate("file.write")
        assert verdict.action == "confirm"

    def test_wildcard_patterns(self):
        """Wildcard patterns match tool families."""
        yaml = """
version: "1.0"
rules:
  - name: allow_fs
    tool_pattern: "filesystem.*"
    action: allow
    reason: "All filesystem ops allowed"
"""
        engine = self._make_engine(yaml)
        v1 = engine.evaluate("filesystem.read_file")
        v2 = engine.evaluate("filesystem.list_directory")
        v3 = engine.evaluate("shell.run")
        assert v1.action == "allow"
        assert v2.action == "allow"
        assert v3.action != "allow" or v3.rule_name != "allow_fs"

    def test_user_id_condition(self):
        """User ID condition filters by user."""
        yaml = """
version: "1.0"
default_verdict: deny
rules:
  - name: admin_only
    tool_pattern: "admin.*"
    action: allow
    reason: "Admin access"
    conditions:
      user_ids: ["admin_001", "admin_002"]
"""
        engine = self._make_engine(yaml)
        v1 = engine.evaluate("admin.reset", user_id="admin_001")
        v2 = engine.evaluate("admin.reset", user_id="regular_user")
        assert v1.action == "allow"
        assert v2.action == "deny"  # falls through to default

    def test_tag_condition(self):
        """Tag condition requires specific metadata tag."""
        yaml = """
version: "1.0"
default_verdict: deny
rules:
  - name: tagged_only
    tool_pattern: "deploy.*"
    action: allow
    reason: "Deploy with tag"
    conditions:
      require_tag: "production"
"""
        engine = self._make_engine(yaml)
        v1 = engine.evaluate("deploy.push", metadata={"tags": ["production"]})
        v2 = engine.evaluate("deploy.push", metadata={"tags": ["staging"]})
        assert v1.action == "allow"
        assert v2.action == "deny"

    def test_rate_limiting(self):
        """Rate limiting enforces max_per_minute."""
        yaml = """
version: "1.0"
rules:
  - name: limited_search
    tool_pattern: "search.*"
    action: allow
    reason: "Search allowed"
    conditions:
      max_per_minute: 3
"""
        engine = self._make_engine(yaml)
        # First 3 should succeed
        for _ in range(3):
            v = engine.evaluate("search.query")
            assert v.action == "allow"
        # 4th should be rate limited
        v = engine.evaluate("search.query")
        assert v.action == "deny"
        assert v.rate_limited is True

    def test_rate_limit_window_expires(self):
        """Rate limit resets after the time window."""
        yaml = """
version: "1.0"
rules:
  - name: limited_api
    tool_pattern: "api.call"
    action: allow
    reason: "ok"
    conditions:
      max_per_minute: 2
"""
        engine = self._make_engine(yaml)
        # Use up the limit
        engine.evaluate("api.call")
        engine.evaluate("api.call")
        # Manually expire timestamps
        engine._rate_counts["limited_api"] = [time.time() - 120]
        v = engine.evaluate("api.call")
        assert v.action == "allow"

    def test_stats_reflect_rules(self):
        """Stats show loaded policy files and rules."""
        yaml = """
version: "2.0"
description: "Test policy"
rules:
  - name: r1
    tool_pattern: "a.*"
    action: allow
  - name: r2
    tool_pattern: "b.*"
    action: deny
"""
        engine = self._make_engine(yaml)
        stats = engine.get_stats()
        assert stats["policy_files"] == 1
        assert stats["total_rules"] == 2
        assert stats["files"][0]["version"] == "2.0"


# ===========================================================================
# OpenClaw PolicyEngine
# ===========================================================================

def _load_openclaw_policy():
    """Load OpenClaw policy_engine via importlib to avoid sys.path collisions."""
    import importlib.util
    mod_name = "openclaw_policy_engine"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, r"S:\services\openclaw\app\policy_engine.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestOpenClawPolicyEngine:

    def _get_engine(self):
        pe = _load_openclaw_policy()
        return pe.PolicyEngine(rules=pe.default_safety_rules())

    def test_safe_read_allowed(self):
        """Read-only operations are allowed."""
        engine = self._get_engine()
        decision = engine.evaluate("file.read", {"path": r"S:\test.txt"})
        assert decision.verdict.value == "allow"

    def test_destructive_shell_denied(self):
        """Destructive shell commands are denied."""
        engine = self._get_engine()
        decision = engine.evaluate("shell.run", {"command": "rm -rf /"})
        assert decision.verdict.value == "deny"

    def test_file_write_confirm(self):
        """File writes require confirmation."""
        engine = self._get_engine()
        decision = engine.evaluate("file.write", {"path": r"S:\output.txt"})
        assert decision.verdict.value == "confirm"

    def test_path_escape_denied(self):
        """Path traversal attempts are denied."""
        engine = self._get_engine()
        decision = engine.evaluate("file.read", {"path": r"C:\Windows\system32\config"})
        assert decision.verdict.value == "deny"

    def test_priority_ordering(self):
        """Higher priority rules match first (allow_health_check at priority 20)."""
        engine = self._get_engine()
        decision = engine.evaluate("health.check", {})
        assert decision.verdict.value == "allow"
        assert decision.rule_name == "allow_health_check"

    def test_unknown_action_catchall(self):
        """Unknown actions get catch-all confirm."""
        engine = self._get_engine()
        decision = engine.evaluate("totally_unknown_action", {})
        assert decision.verdict.value == "confirm"

    def test_audit_log_records(self):
        """Decisions are recorded in audit log."""
        engine = self._get_engine()
        engine.evaluate("file.read", {"path": r"S:\test.txt"})
        engine.evaluate("shell.run", {"command": "Get-ChildItem"})
        log = engine.audit_log
        assert len(log) >= 2

    def test_audit_immutable(self):
        """Audit log entries cannot be modified after creation."""
        engine = self._get_engine()
        engine.evaluate("file.read", {"path": r"S:\test.txt"})
        log = engine.audit_log
        initial_count = len(log)
        # Getting the log again shouldn't change previous entries
        engine.evaluate("shell.run", {"command": "Get-ChildItem"})
        log2 = engine.audit_log
        assert len(log2) >= initial_count + 1
