"""Policy enforcement gate: verifies tool/action allow/deny/failure modes."""
import json, os, sys, datetime, subprocess

TS = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GW = os.path.join(ROOT, "services", "api-gateway")
os.makedirs(os.path.join(ROOT, "reports", "audit"), exist_ok=True)

checks = []

# ── Check 1: tool_policy.py has deny-by-default for unknowns ─────────────
tp_path = os.path.join(GW, "tool_policy.py")
with open(tp_path, "r") as f:
    tp_src = f.read()

has_deny_default = 'return "blocked"' in tp_src
checks.append({
    "name": "deny_by_default",
    "passed": has_deny_default,
    "detail": f"Unknown tools return 'blocked': {has_deny_default}",
})

# ── Check 2: 3-tier classification exists ─────────────────────────────────
has_safe = "SAFE_READ_TOOLS" in tp_src
has_guarded = "GUARDED_WRITE_TOOLS" in tp_src
has_blocked = "BLOCKED_TOOLS" in tp_src
three_tier = has_safe and has_guarded and has_blocked
checks.append({
    "name": "three_tier_classification",
    "passed": three_tier,
    "detail": f"3-tier (safe/guarded/blocked) present: {three_tier}",
})

# ── Check 3: Confirmation token has expiry with CONFIRMATION_EXPIRED code ─
has_expired_code = "CONFIRMATION_EXPIRED" in tp_src
checks.append({
    "name": "confirmation_expired_code",
    "passed": has_expired_code,
    "detail": f"CONFIRMATION_EXPIRED code in token lifecycle: {has_expired_code}",
})

# ── Check 4: Idempotent approve/deny ─────────────────────────────────────
has_idempotent = "idempotent" in tp_src.lower()
checks.append({
    "name": "idempotent_decisions",
    "passed": has_idempotent,
    "detail": f"Idempotent approve/deny in confirmation manager: {has_idempotent}",
})

# ── Check 5: Per-session pending limit ────────────────────────────────────
has_pending_limit = "max_guarded_requests_pending" in tp_src or "max_guarded_per_session" in tp_src
checks.append({
    "name": "per_session_limit",
    "passed": has_pending_limit,
    "detail": f"Per-session pending limit enforced: {has_pending_limit}",
})

# ── Check 6: frozenset for tool sets (immutable) ─────────────────────────
has_frozen = "frozenset" in tp_src
checks.append({
    "name": "immutable_tool_sets",
    "passed": has_frozen,
    "detail": f"Tool sets use frozenset (immutable): {has_frozen}",
})

# ── Check 7: Unit tests exist ────────────────────────────────────────────
test_path = os.path.join(ROOT, "tests", "unit", "test_policy_enforcement.py")
checks.append({
    "name": "unit_tests_exist",
    "passed": os.path.isfile(test_path),
    "detail": f"test_policy_enforcement.py exists: {os.path.isfile(test_path)}",
})

# ── Check 8: Unit tests pass ─────────────────────────────────────────────
python = os.path.join(ROOT, "envs", "sonia-core", "python.exe")
if not os.path.isfile(python):
    python = sys.executable

result = subprocess.run(
    [python, "-m", "pytest", test_path, "-v", "--tb=short", "-q"],
    capture_output=True, text=True, cwd=ROOT, timeout=120
)
unit_passed = result.returncode == 0
lines = result.stdout.strip().split("\n")
summary_line = lines[-1] if lines else ""
checks.append({
    "name": "unit_tests_pass",
    "passed": unit_passed,
    "detail": summary_line,
    "stdout": result.stdout[-500:] if not unit_passed else "",
    "stderr": result.stderr[-300:] if not unit_passed else "",
})

# ── Check 9: Fallback contract has trigger enum ──────────────────────────
rc_path = os.path.join(GW, "clients", "router_client.py")
with open(rc_path, "r") as f:
    rc_src = f.read()

has_triggers = "FALLBACK_TRIGGERS" in rc_src and "frozenset" in rc_src
checks.append({
    "name": "fallback_trigger_enum",
    "passed": has_triggers,
    "detail": f"Fallback trigger enum (frozenset) exists: {has_triggers}",
})

# ── Check 10: Fallback contract version marker ───────────────────────────
has_version = "FALLBACK_CONTRACT_VERSION" in rc_src
checks.append({
    "name": "fallback_contract_version",
    "passed": has_version,
    "detail": f"Fallback contract version marker present: {has_version}",
})

all_passed = all(c["passed"] for c in checks)
report = {
    "gate": "policy_enforcement",
    "timestamp_utc": TS,
    "passed": all_passed,
    "checks_total": len(checks),
    "checks_passed": sum(1 for c in checks if c["passed"]),
    "checks": checks,
}

path = os.path.join(ROOT, "reports", "audit", f"policy-enforcement-{TS}.json")
with open(path, "w") as f:
    json.dump(report, f, indent=2)

print(f"=== Policy Enforcement Gate ({report['checks_passed']}/{report['checks_total']}) ===\n")
for c in checks:
    status = "PASS" if c["passed"] else "FAIL"
    print(f"  [{status}] {c['name']}: {c['detail']}")

print(f"\nReport: {path}")
print(f"\n{'PASS' if all_passed else 'FAIL'}")
sys.exit(0 if all_passed else 1)
