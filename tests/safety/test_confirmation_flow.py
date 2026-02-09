"""
Action Safety Layer - Confirmation Flow Tests (F1-F17)

Tests the full confirmation token lifecycle: mint, redeem, expire,
replay denial, explicit deny, TTL expiry, max pending eviction,
and end-to-end guard flow.
"""

import sys
import time
sys.path.insert(0, r"S:\services\openclaw")

from app.policy_engine import ActionVerdict, PolicyEngine, default_safety_rules
from app.confirmations import (
    TokenState, ConfirmationToken, RedeemResult, ConfirmationManager,
)
from app.action_guard import ActionGuard, GuardResult

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
print("Test Suite: Confirmation Flow (F1-F17)")
print("=" * 60)

# -- F1: Mint token basics --
print("\n--- F1: Mint token ---")
mgr = ConfirmationManager(ttl_seconds=10.0)
tok = mgr.mint_token("file.write", {"path": "S:\\tmp\\x"}, "f1")
check("F1a", tok.token_id.startswith("ctk_"), "Token prefix")
check("F1b", tok.state == TokenState.PENDING, "Pending state")
check("F1c", tok.action == "file.write", "Action preserved")
check("F1d", tok.remaining_seconds > 0, "TTL remaining")

# -- F2: Redeem happy path --
print("\n--- F2: Redeem ---")
r = mgr.redeem_token(tok.token_id, "f2")
check("F2a", r.accepted, "Accepted")
check("F2b", r.state == TokenState.APPROVED, "Approved state")

# -- F3: Replay denial --
print("\n--- F3: Replay denial ---")
r = mgr.redeem_token(tok.token_id, "f3")
check("F3a", not r.accepted, "Rejected")
check("F3b", r.state == TokenState.REPLAYED, "Replayed state")
check("F3c", "already used" in r.reason.lower(), "Reason")

# -- F4: Nonexistent token --
print("\n--- F4: Nonexistent token ---")
r = mgr.redeem_token("ctk_bogus", "f4")
check("F4a", not r.accepted, "Not found")
check("F4b", "not found" in r.reason.lower(), "Reason")

# -- F5: TTL expiry --
print("\n--- F5: TTL expiry ---")
mgr2 = ConfirmationManager(ttl_seconds=0.05)
tok2 = mgr2.mint_token("shell.run", {"command": "ls"}, "f5a")
time.sleep(0.1)
r = mgr2.redeem_token(tok2.token_id, "f5b")
check("F5a", not r.accepted, "Expired rejected")
check("F5b", r.state == TokenState.EXPIRED, "Expired state")

# -- F6: Explicit deny --
print("\n--- F6: Explicit deny ---")
mgr3 = ConfirmationManager(ttl_seconds=60.0)
tok3 = mgr3.mint_token("browser.open", {"url": "https://x.com"}, "f6a")
r = mgr3.deny_token(tok3.token_id, "f6b", "No thanks")
check("F6a", not r.accepted, "Deny not accepted")
check("F6b", r.state == TokenState.DENIED, "Denied state")
# Post-deny redeem
r2 = mgr3.redeem_token(tok3.token_id, "f6c")
check("F6c", not r2.accepted, "Post-deny redeem rejected")

# -- F7: Max pending eviction --
print("\n--- F7: Max pending eviction ---")
mgr4 = ConfirmationManager(ttl_seconds=60.0, max_pending=2)
t1 = mgr4.mint_token("a1", {}, "f7a")
t2 = mgr4.mint_token("a2", {}, "f7b")
t3 = mgr4.mint_token("a3", {}, "f7c")
check("F7a", mgr4.get_token(t1.token_id).state == TokenState.EXPIRED, "Oldest evicted")
check("F7b", mgr4.get_token(t3.token_id).state == TokenState.PENDING, "Newest pending")

# -- F8: Pending query --
print("\n--- F8: Pending query ---")
mgr5 = ConfirmationManager(ttl_seconds=60.0)
t1 = mgr5.mint_token("a", {}, "f8a")
t2 = mgr5.mint_token("b", {}, "f8b")
mgr5.redeem_token(t1.token_id, "f8c")
check("F8a", mgr5.pending_count == 1, "1 pending")

# -- F9: Event log --
print("\n--- F9: Event log ---")
events = mgr5.event_log
check("F9a", len(events) >= 3, "At least 3 events")
types = [e["event"] for e in events]
check("F9b", "minted" in types, "Minted logged")
check("F9c", "redeemed" in types, "Redeemed logged")

# -- F10: Token serialisation --
print("\n--- F10: Token serialisation ---")
mgr6 = ConfirmationManager(ttl_seconds=60.0)
tok6 = mgr6.mint_token("test", {"key": "val"}, "f10")
d = tok6.to_dict()
check("F10a", d["state"] == "pending", "State serialised")
check("F10b", d["remaining_seconds"] > 0, "TTL in dict")

# -- F11: Guard ALLOW path --
print("\n--- F11: Guard ALLOW ---")
engine = PolicyEngine(rules=default_safety_rules())
conf = ConfirmationManager(ttl_seconds=60.0)
guard = ActionGuard(engine, conf)
r = guard.guard("file.read", {"path": "S:\\x"}, trace_id="f11")
check("F11a", r.proceed, "Proceeds")
check("F11b", not r.needs_confirmation, "No confirmation")

# -- F12: Guard DENY path --
print("\n--- F12: Guard DENY ---")
r = guard.guard("shell.run", {"command": "Remove-Item foo"}, trace_id="f12")
check("F12a", r.denied, "Denied")
check("F12b", not r.proceed, "Not proceed")

# -- F13: Guard CONFIRM -> mint token --
print("\n--- F13: Guard CONFIRM mint ---")
r = guard.guard("file.write", {"path": "S:\\tmp\\test"}, trace_id="f13")
check("F13a", r.needs_confirmation, "Needs confirmation")
check("F13b", r.confirmation_token is not None, "Token minted")

# -- F14: Guard CONFIRM -> redeem token --
print("\n--- F14: Guard CONFIRM redeem ---")
tok_id = r.confirmation_token.token_id
r2 = guard.guard("file.write", {"path": "S:\\tmp\\test"},
    context={"approval_token": tok_id}, trace_id="f14")
check("F14a", r2.proceed, "Proceeds with token")
check("F14b", r2.redeem_result.accepted, "Token accepted")

# -- F15: Guard replay rejection --
print("\n--- F15: Guard replay ---")
r3 = guard.guard("file.write", {"path": "S:\\tmp\\test"},
    context={"approval_token": tok_id}, trace_id="f15")
check("F15a", not r3.proceed, "Replay blocked")
check("F15b", r3.denied, "Marked denied")

# -- F16: Guard deny_pending --
print("\n--- F16: Guard deny_pending ---")
r = guard.guard("file.write", {"path": "S:\\tmp\\deny_me"}, trace_id="f16a")
deny_tok = r.confirmation_token.token_id
dr = guard.deny_pending(deny_tok, "f16b", "Nope")
check("F16a", not dr.accepted, "Deny result")
check("F16b", dr.state == TokenState.DENIED, "Denied state")

# -- F17: GuardResult serialisation --
print("\n--- F17: GuardResult serialisation ---")
r = guard.guard("file.read", {"path": "S:\\x"}, trace_id="f17")
d = r.to_dict()
check("F17a", d["proceed"] == True, "proceed in dict")
check("F17b", "policy_decision" in d, "policy_decision in dict")

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
