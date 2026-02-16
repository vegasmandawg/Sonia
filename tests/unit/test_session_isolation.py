"""v3.7 M1 — Session Isolation Guardrail Tests.

Validates:
- Session context validation (required fields)
- Cross-session read blocking
- Cross-persona read/write blocking
- Write reason code enforcement
- Policy trace field generation
- Scoped filter generation
- Guard statistics tracking
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join("S:", os.sep, "services", "api-gateway"))

from session_isolation import (
    SessionContext,
    SessionIsolationGuard,
    IsolationViolation,
    WriteReasonCode,
    PolicyTraceField,
)


class TestSessionContextValidation(unittest.TestCase):
    """Session context must have required fields."""

    def test_valid_context(self):
        ctx = SessionContext(session_id="ses_abc", user_id="user_1")
        ctx.validate()  # should not raise

    def test_missing_session_id(self):
        ctx = SessionContext(session_id="", user_id="user_1")
        with self.assertRaises(IsolationViolation) as cm:
            ctx.validate()
        self.assertEqual(cm.exception.code, "MISSING_SESSION")

    def test_missing_user_id(self):
        ctx = SessionContext(session_id="ses_abc", user_id="")
        with self.assertRaises(IsolationViolation) as cm:
            ctx.validate()
        self.assertEqual(cm.exception.code, "MISSING_USER")

    def test_default_persona(self):
        ctx = SessionContext(session_id="ses_abc", user_id="user_1")
        self.assertEqual(ctx.persona_id, "default")


class TestReadIsolation(unittest.TestCase):
    """Memory reads must be scoped to the requesting session's user+persona."""

    def setUp(self):
        self.guard = SessionIsolationGuard()
        self.ctx_a = SessionContext(session_id="ses_a", user_id="user_1", persona_id="sonia")
        self.ctx_b = SessionContext(session_id="ses_b", user_id="user_2", persona_id="sonia")
        self.guard.register_session(self.ctx_a)
        self.guard.register_session(self.ctx_b)

    def test_same_user_same_persona_allowed(self):
        result = self.guard.validate_read(self.ctx_a, target_user_id="user_1", target_persona_id="sonia")
        self.assertTrue(result)

    def test_cross_user_read_blocked(self):
        with self.assertRaises(IsolationViolation) as cm:
            self.guard.validate_read(self.ctx_a, target_user_id="user_2")
        self.assertEqual(cm.exception.code, "CROSS_USER_READ")

    def test_cross_persona_read_blocked(self):
        with self.assertRaises(IsolationViolation) as cm:
            self.guard.validate_read(self.ctx_a, target_user_id="user_1", target_persona_id="other_persona")
        self.assertEqual(cm.exception.code, "CROSS_PERSONA_READ")

    def test_violation_increments_counter(self):
        initial = self.guard.get_stats()["total_violations"]
        try:
            self.guard.validate_read(self.ctx_a, target_user_id="user_2")
        except IsolationViolation:
            pass
        self.assertEqual(self.guard.get_stats()["total_violations"], initial + 1)


class TestWriteIsolation(unittest.TestCase):
    """Memory writes must have valid reason codes and respect persona scope."""

    def setUp(self):
        self.guard = SessionIsolationGuard()
        self.ctx = SessionContext(
            session_id="ses_w", user_id="user_1",
            persona_id="sonia", correlation_id="req_test123",
        )
        self.guard.register_session(self.ctx)

    def test_valid_write_returns_trace(self):
        trace = self.guard.validate_write(self.ctx, write_reason="turn_raw", target_persona_id="sonia")
        self.assertIsInstance(trace, PolicyTraceField)
        self.assertEqual(trace.session_id, "ses_w")
        self.assertEqual(trace.write_reason, "turn_raw")
        self.assertEqual(trace.correlation_id, "req_test123")
        self.assertEqual(trace.policy_version, "1.0")

    def test_invalid_write_reason_blocked(self):
        with self.assertRaises(IsolationViolation) as cm:
            self.guard.validate_write(self.ctx, write_reason="arbitrary_junk")
        self.assertEqual(cm.exception.code, "INVALID_WRITE_REASON")

    def test_cross_persona_write_blocked(self):
        with self.assertRaises(IsolationViolation) as cm:
            self.guard.validate_write(self.ctx, write_reason="turn_raw", target_persona_id="other")
        self.assertEqual(cm.exception.code, "CROSS_PERSONA_WRITE")

    def test_all_write_reasons_valid(self):
        for reason in WriteReasonCode:
            trace = self.guard.validate_write(self.ctx, write_reason=reason.value, target_persona_id="sonia")
            self.assertEqual(trace.write_reason, reason.value)

    def test_trace_to_dict(self):
        trace = self.guard.validate_write(self.ctx, write_reason="turn_summary", target_persona_id="sonia")
        d = trace.to_dict()
        self.assertIn("session_id", d)
        self.assertIn("policy_version", d)
        self.assertIn("write_reason", d)


class TestScopedFilters(unittest.TestCase):
    """Scoped filters constrain memory queries to session scope."""

    def test_filters_include_user_and_persona(self):
        guard = SessionIsolationGuard()
        ctx = SessionContext(session_id="ses_f", user_id="u1", persona_id="p1")
        filters = guard.get_scoped_filters(ctx)
        self.assertEqual(filters["user_id"], "u1")
        self.assertEqual(filters["persona_id"], "p1")

    def test_filters_reject_empty_context(self):
        guard = SessionIsolationGuard()
        ctx = SessionContext(session_id="", user_id="u1")
        with self.assertRaises(IsolationViolation):
            guard.get_scoped_filters(ctx)


class TestGuardLifecycle(unittest.TestCase):
    """Guard tracks active sessions and provides statistics."""

    def test_register_and_unregister(self):
        guard = SessionIsolationGuard()
        ctx = SessionContext(session_id="ses_lc", user_id="u1")
        guard.register_session(ctx)
        self.assertEqual(guard.get_stats()["active_sessions"], 1)
        guard.unregister_session("ses_lc")
        self.assertEqual(guard.get_stats()["active_sessions"], 0)

    def test_operation_count_tracks(self):
        guard = SessionIsolationGuard()
        ctx = SessionContext(session_id="ses_op", user_id="u1")
        guard.register_session(ctx)
        guard.validate_read(ctx, target_user_id="u1")
        guard.validate_write(ctx, write_reason="turn_raw")
        self.assertEqual(guard.get_stats()["total_operations"], 2)

    def test_unregister_nonexistent_safe(self):
        guard = SessionIsolationGuard()
        guard.unregister_session("nonexistent")  # should not raise


if __name__ == "__main__":
    unittest.main()
