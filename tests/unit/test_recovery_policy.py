"""v3.7 M2 — Recovery Policy Engine Tests.

Validates:
- Recovery policy table completeness (10 rules)
- Deterministic lookup (state + trigger -> action)
- Cooldown enforcement (no double-fire)
- Restart budget tracking (window-bounded)
- Decision log immutability and bounded growth
- Stats accuracy
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join("S:", os.sep, "services", "api-gateway"))

from recovery_policy import (
    RecoveryTrigger,
    RecoveryAction,
    ServiceState,
    RecoveryRule,
    RestartBudget,
    RecoveryPolicyEngine,
    RECOVERY_POLICY_TABLE,
)


class TestPolicyTableCompleteness(unittest.TestCase):
    """The canonical policy table must cover expected state/trigger combos."""

    def test_table_has_10_rules(self):
        self.assertEqual(len(RECOVERY_POLICY_TABLE), 10)

    def test_all_rules_are_recovery_rule(self):
        for rule in RECOVERY_POLICY_TABLE:
            self.assertIsInstance(rule, RecoveryRule)

    def test_healthy_state_rules_exist(self):
        healthy_rules = [r for r in RECOVERY_POLICY_TABLE if r.state == ServiceState.HEALTHY]
        self.assertGreaterEqual(len(healthy_rules), 2)

    def test_degraded_state_rules_exist(self):
        degraded_rules = [r for r in RECOVERY_POLICY_TABLE if r.state == ServiceState.DEGRADED]
        self.assertGreaterEqual(len(degraded_rules), 2)

    def test_failed_state_rules_exist(self):
        failed_rules = [r for r in RECOVERY_POLICY_TABLE if r.state == ServiceState.FAILED]
        self.assertGreaterEqual(len(failed_rules), 1)

    def test_all_triggers_are_valid_enum(self):
        for rule in RECOVERY_POLICY_TABLE:
            self.assertIsInstance(rule.trigger, RecoveryTrigger)

    def test_all_actions_are_valid_enum(self):
        for rule in RECOVERY_POLICY_TABLE:
            self.assertIsInstance(rule.action, RecoveryAction)


class TestDeterministicLookup(unittest.TestCase):
    """lookup(state, trigger) must return a deterministic rule or None."""

    def setUp(self):
        self.engine = RecoveryPolicyEngine()

    def test_healthy_health_check_failed(self):
        rule = self.engine.lookup(ServiceState.HEALTHY, RecoveryTrigger.HEALTH_CHECK_FAILED)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.action, RecoveryAction.RETRY_WITH_BACKOFF)

    def test_healthy_timeout(self):
        rule = self.engine.lookup(ServiceState.HEALTHY, RecoveryTrigger.TIMEOUT_EXCEEDED)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.action, RecoveryAction.RETRY_WITH_BACKOFF)

    def test_degraded_circuit_breaker_tripped(self):
        rule = self.engine.lookup(ServiceState.DEGRADED, RecoveryTrigger.CIRCUIT_BREAKER_TRIPPED)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.action, RecoveryAction.FAILOVER_TO_FALLBACK)

    def test_failed_process_crashed(self):
        rule = self.engine.lookup(ServiceState.FAILED, RecoveryTrigger.PROCESS_CRASHED)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.action, RecoveryAction.RESTART_SERVICE)

    def test_unknown_combo_returns_none(self):
        # No rule for HEALTHY + PROCESS_CRASHED
        rule = self.engine.lookup(ServiceState.HEALTHY, RecoveryTrigger.PROCESS_CRASHED)
        self.assertIsNone(rule)


class TestCooldownEnforcement(unittest.TestCase):
    """Cooldown must prevent rapid-fire decisions for the same service+trigger."""

    def setUp(self):
        self.engine = RecoveryPolicyEngine()

    def test_first_decision_allowed(self):
        decision = self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        self.assertEqual(decision["action"], RecoveryAction.RETRY_WITH_BACKOFF.value)
        self.assertTrue(decision["allowed"])

    def test_second_decision_within_cooldown_blocked(self):
        self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        decision = self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        self.assertFalse(decision["allowed"])

    def test_different_service_not_blocked(self):
        self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        decision = self.engine.decide(
            "model-router", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        self.assertTrue(decision["allowed"])

    def test_different_trigger_not_blocked(self):
        self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        decision = self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.TIMEOUT_EXCEEDED,
        )
        self.assertTrue(decision["allowed"])


class TestRestartBudget(unittest.TestCase):
    """RestartBudget must enforce window-bounded restart limits."""

    def test_fresh_budget_can_restart(self):
        budget = RestartBudget(max_restarts=3, window_seconds=300.0)
        self.assertTrue(budget.can_restart())

    def test_budget_tracks_remaining(self):
        budget = RestartBudget(max_restarts=3, window_seconds=300.0)
        self.assertEqual(budget.remaining, 3)
        budget.record_restart()
        self.assertEqual(budget.remaining, 2)

    def test_budget_exhaustion(self):
        budget = RestartBudget(max_restarts=2, window_seconds=300.0)
        budget.record_restart()
        budget.record_restart()
        self.assertFalse(budget.can_restart())
        self.assertEqual(budget.remaining, 0)

    def test_budget_window_expiry(self):
        budget = RestartBudget(max_restarts=1, window_seconds=0.01)
        budget.record_restart()
        self.assertFalse(budget.can_restart())
        time.sleep(0.02)
        self.assertTrue(budget.can_restart())

    def test_exhausted_property(self):
        budget = RestartBudget(max_restarts=1, window_seconds=300.0)
        self.assertFalse(budget.exhausted)
        budget.record_restart()
        self.assertTrue(budget.exhausted)


class TestDecisionLog(unittest.TestCase):
    """Decision log must be bounded and queryable."""

    def setUp(self):
        self.engine = RecoveryPolicyEngine()

    def test_decision_recorded(self):
        self.engine.decide(
            "api-gateway", ServiceState.HEALTHY,
            RecoveryTrigger.HEALTH_CHECK_FAILED,
        )
        log = self.engine.get_decision_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["service"], "api-gateway")

    def test_log_limit(self):
        for i in range(5):
            self.engine.decide(
                f"svc-{i}", ServiceState.HEALTHY,
                RecoveryTrigger.HEALTH_CHECK_FAILED,
            )
        log = self.engine.get_decision_log(limit=3)
        self.assertEqual(len(log), 3)

    def test_no_rule_decision_logged(self):
        self.engine.decide("svc", ServiceState.HEALTHY, RecoveryTrigger.PROCESS_CRASHED)
        log = self.engine.get_decision_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["action"], RecoveryAction.NO_ACTION.value)


class TestEngineStats(unittest.TestCase):
    """Engine stats must reflect current state."""

    def test_initial_stats(self):
        engine = RecoveryPolicyEngine()
        stats = engine.get_stats()
        self.assertEqual(stats["total_decisions"], 0)
        self.assertEqual(stats["total_rules"], 10)

    def test_stats_after_decisions(self):
        engine = RecoveryPolicyEngine()
        engine.decide("svc", ServiceState.HEALTHY, RecoveryTrigger.HEALTH_CHECK_FAILED)
        engine.decide("svc2", ServiceState.DEGRADED, RecoveryTrigger.CIRCUIT_BREAKER_TRIPPED)
        stats = engine.get_stats()
        self.assertEqual(stats["total_decisions"], 2)

    def test_policy_table_exposed(self):
        engine = RecoveryPolicyEngine()
        table = engine.get_policy_table()
        self.assertEqual(len(table), 10)
        self.assertIn("state", table[0])
        self.assertIn("trigger", table[0])
        self.assertIn("action", table[0])


if __name__ == "__main__":
    unittest.main()
