"""
Policy enforcement tests for v3.6 P1.

Proves:
  1. Tool policy classify_tool returns correct tier for all known tools.
  2. Unknown tools are blocked by default (deny-by-default).
  3. Confirmation token lifecycle: mint -> approve/deny -> idempotent re-call.
  4. Confirmation expiry returns CONFIRMATION_EXPIRED code.
  5. Per-session pending limit is enforced.
  6. Rate limiter denies over-limit clients with 429.
  7. Rate limiter allows normal traffic.
"""
import importlib.util, os, sys, time, asyncio, unittest

# ── Load tool_policy module ───────────────────────────────────────────────────
_GW = r"S:\services\api-gateway"
spec = importlib.util.spec_from_file_location("tool_policy", os.path.join(_GW, "tool_policy.py"))
tp_mod = importlib.util.module_from_spec(spec)
sys.modules["tool_policy"] = tp_mod
spec.loader.exec_module(tp_mod)

classify_tool = tp_mod.classify_tool
ConfirmationToken = tp_mod.ConfirmationToken
GatewayConfirmationManager = tp_mod.GatewayConfirmationManager
SAFE_READ_TOOLS = tp_mod.SAFE_READ_TOOLS
GUARDED_WRITE_TOOLS = tp_mod.GUARDED_WRITE_TOOLS
BLOCKED_TOOLS = tp_mod.BLOCKED_TOOLS

# ── Load rate_limiter module ──────────────────────────────────────────────────
spec_rl = importlib.util.spec_from_file_location("rate_limiter", os.path.join(r"S:\services\shared", "rate_limiter.py"))
rl_mod = importlib.util.module_from_spec(spec_rl)
sys.modules["rate_limiter"] = rl_mod
spec_rl.loader.exec_module(rl_mod)
RateLimiter = rl_mod.RateLimiter


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Classification Tests ──────────────────────────────────────────────────────

class TestClassifyToolDenyByDefault(unittest.TestCase):
    """Tool classification must deny-by-default for unknown tools."""

    def test_safe_read_tools(self):
        for tool in SAFE_READ_TOOLS:
            self.assertEqual(classify_tool(tool), "safe_read", f"{tool} should be safe_read")

    def test_guarded_write_tools(self):
        for tool in GUARDED_WRITE_TOOLS:
            self.assertEqual(classify_tool(tool), "guarded_write", f"{tool} should be guarded_write")

    def test_unknown_tool_blocked(self):
        self.assertEqual(classify_tool("totally.unknown"), "blocked")

    def test_empty_name_blocked(self):
        self.assertEqual(classify_tool(""), "blocked")

    def test_partial_name_blocked(self):
        self.assertEqual(classify_tool("file"), "blocked")

    def test_case_sensitive(self):
        """Tool names are case-sensitive — File.Read != file.read."""
        self.assertEqual(classify_tool("File.Read"), "blocked")
        self.assertEqual(classify_tool("SHELL.RUN"), "blocked")

    def test_blocked_set_initially_empty(self):
        self.assertEqual(len(BLOCKED_TOOLS), 0)

    def test_safe_and_guarded_disjoint(self):
        overlap = SAFE_READ_TOOLS & GUARDED_WRITE_TOOLS
        self.assertEqual(overlap, frozenset(), f"Overlap: {overlap}")


# ── Confirmation Lifecycle Tests ──────────────────────────────────────────────

class TestConfirmationLifecycle(unittest.TestCase):
    """Full mint → approve/deny → idempotent lifecycle."""

    def test_mint_approve(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60)
        token = _run(mgr.create("s1", "t1", "file.write", {"path": "/tmp/x"}))
        self.assertEqual(token.status, "pending")
        result = _run(mgr.approve(token.confirmation_id))
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "approved")

    def test_mint_deny(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60)
        token = _run(mgr.create("s1", "t1", "shell.run", {"command": "rm -rf"}))
        result = _run(mgr.deny(token.confirmation_id, "Too dangerous"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "denied")

    def test_approve_idempotent(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60)
        token = _run(mgr.create("s1", "t1", "file.write", {}))
        _run(mgr.approve(token.confirmation_id))
        result = _run(mgr.approve(token.confirmation_id))
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("idempotent", False))

    def test_deny_idempotent(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60)
        token = _run(mgr.create("s1", "t1", "file.write", {}))
        _run(mgr.deny(token.confirmation_id))
        result = _run(mgr.deny(token.confirmation_id))
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("idempotent", False))

    def test_approve_after_deny_fails(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60)
        token = _run(mgr.create("s1", "t1", "file.write", {}))
        _run(mgr.deny(token.confirmation_id))
        result = _run(mgr.approve(token.confirmation_id))
        self.assertFalse(result["ok"])

    def test_not_found(self):
        mgr = GatewayConfirmationManager()
        result = _run(mgr.approve("cfm_nonexistent"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "not_found")


class TestConfirmationExpiry(unittest.TestCase):
    """Expired tokens must return CONFIRMATION_EXPIRED code."""

    def test_expired_approve_returns_code(self):
        mgr = GatewayConfirmationManager(ttl_seconds=0.01)
        token = _run(mgr.create("s1", "t1", "file.write", {}))
        time.sleep(0.02)
        result = _run(mgr.approve(token.confirmation_id))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("code"), "CONFIRMATION_EXPIRED")

    def test_expired_deny_returns_code(self):
        mgr = GatewayConfirmationManager(ttl_seconds=0.01)
        token = _run(mgr.create("s1", "t1", "file.write", {}))
        time.sleep(0.02)
        result = _run(mgr.deny(token.confirmation_id))
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("code"), "CONFIRMATION_EXPIRED")


class TestPerSessionPendingLimit(unittest.TestCase):
    """Per-session pending limit must be enforced."""

    def test_limit_enforced(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60, max_guarded_requests_pending=3)
        for i in range(3):
            _run(mgr.create("s1", f"t{i}", "file.write", {}))
        with self.assertRaises(RuntimeError):
            _run(mgr.create("s1", "t3", "file.write", {}))

    def test_different_sessions_independent(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60, max_guarded_requests_pending=2)
        _run(mgr.create("s1", "t1", "file.write", {}))
        _run(mgr.create("s1", "t2", "file.write", {}))
        # s2 has its own limit
        token = _run(mgr.create("s2", "t1", "file.write", {}))
        self.assertEqual(token.status, "pending")

    def test_approved_frees_slot(self):
        mgr = GatewayConfirmationManager(ttl_seconds=60, max_guarded_requests_pending=2)
        t1 = _run(mgr.create("s1", "t1", "file.write", {}))
        _run(mgr.create("s1", "t2", "file.write", {}))
        _run(mgr.approve(t1.confirmation_id))
        # Now slot freed
        t3 = _run(mgr.create("s1", "t3", "file.write", {}))
        self.assertEqual(t3.status, "pending")


# ── Rate Limiter Tests ────────────────────────────────────────────────────────

class TestRateLimiterEnforcement(unittest.TestCase):
    """Rate limiter denies over-limit clients."""

    def test_allows_within_limit(self):
        rl = RateLimiter(rate=100, burst=5)
        for _ in range(5):
            allowed, _ = rl.check("client1")
            self.assertTrue(allowed)

    def test_denies_over_limit(self):
        rl = RateLimiter(rate=1, burst=2)
        rl.check("client1")
        rl.check("client1")
        allowed, retry_after = rl.check("client1")
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)

    def test_per_client_isolation(self):
        rl = RateLimiter(rate=1, burst=1)
        rl.check("a")
        # a is now at limit, b should still be fine
        allowed, _ = rl.check("b")
        self.assertTrue(allowed)

    def test_retry_after_is_numeric(self):
        rl = RateLimiter(rate=1, burst=1)
        rl.check("c")
        _, retry_after = rl.check("c")
        self.assertIsInstance(retry_after, (int, float))


if __name__ == "__main__":
    unittest.main()
