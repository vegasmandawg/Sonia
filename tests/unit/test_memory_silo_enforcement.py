"""v3.7 M1 — Memory Silo Enforcement Tests.

Validates:
- Default persona silo registration
- Cross-persona read blocking (and allow override)
- Write type enforcement per silo policy
- Conflict resolution determinism (all 4 strategies)
- Ledger immutability and bounded growth
- Memory type priority ordering
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join("S:", os.sep, "services", "api-gateway"))

from memory_silo import (
    MemorySiloEnforcer,
    SiloPolicy,
    ConflictResolution,
    LedgerEntry,
    MEMORY_TYPE_PRIORITY,
)


class TestDefaultSiloRegistration(unittest.TestCase):
    """Enforcer registers a default persona silo on init."""

    def test_default_persona_exists(self):
        enforcer = MemorySiloEnforcer()
        self.assertIn("default", enforcer.get_stats()["registered_personas"])

    def test_custom_silo_registration(self):
        enforcer = MemorySiloEnforcer()
        enforcer.register_silo(SiloPolicy(persona_id="sonia"))
        self.assertIn("sonia", enforcer.get_stats()["registered_personas"])
        self.assertEqual(enforcer.get_stats()["persona_count"], 2)


class TestCrossPersonaReadBlocking(unittest.TestCase):
    """Cross-persona reads are blocked unless policy allows."""

    def setUp(self):
        self.enforcer = MemorySiloEnforcer()
        self.enforcer.register_silo(SiloPolicy(persona_id="sonia"))
        self.enforcer.register_silo(SiloPolicy(
            persona_id="admin", allow_cross_persona_read=True,
        ))

    def test_same_persona_allowed(self):
        self.assertTrue(self.enforcer.enforce_read("sonia", "sonia"))

    def test_cross_persona_blocked(self):
        with self.assertRaises(ValueError) as cm:
            self.enforcer.enforce_read("sonia", "admin")
        self.assertIn("Cross-persona read blocked", str(cm.exception))

    def test_cross_persona_allowed_by_policy(self):
        # admin policy has allow_cross_persona_read=True
        self.assertTrue(self.enforcer.enforce_read("admin", "sonia"))


class TestWriteTypeEnforcement(unittest.TestCase):
    """Silo policy can restrict which memory types a persona can write."""

    def setUp(self):
        self.enforcer = MemorySiloEnforcer()
        self.enforcer.register_silo(SiloPolicy(
            persona_id="restricted",
            allowed_write_types=["turn_raw", "turn_summary"],
        ))

    def test_allowed_type_passes(self):
        entry = self.enforcer.enforce_write(
            persona_id="restricted", memory_type="turn_raw",
            session_id="s1", user_id="u1", write_reason="turn_raw",
        )
        self.assertIsInstance(entry, LedgerEntry)
        self.assertEqual(entry.memory_type, "turn_raw")

    def test_disallowed_type_blocked(self):
        with self.assertRaises(ValueError) as cm:
            self.enforcer.enforce_write(
                persona_id="restricted", memory_type="system_state",
                session_id="s1", user_id="u1", write_reason="system_state",
            )
        self.assertIn("does not allow", str(cm.exception))

    def test_unrestricted_persona_allows_all(self):
        # Default persona has allowed_write_types=None (all allowed)
        entry = self.enforcer.enforce_write(
            persona_id="default", memory_type="system_state",
            session_id="s1", user_id="u1", write_reason="system_state",
        )
        self.assertEqual(entry.memory_type, "system_state")


class TestConflictResolution(unittest.TestCase):
    """Conflict resolution is deterministic across all strategies."""

    def setUp(self):
        self.enforcer = MemorySiloEnforcer()

    def _make_entry(self, entry_id, memory_type="turn_raw", **kwargs):
        """Create a LedgerEntry for testing."""
        defaults = {
            "timestamp": 0.0,
            "session_id": "s1",
            "user_id": "u1",
            "persona_id": "default",
            "operation": "write",
            "write_reason": memory_type,
        }
        defaults.update(kwargs)
        return LedgerEntry(entry_id=entry_id, memory_type=memory_type, **defaults)

    def test_last_write_wins(self):
        old = self._make_entry("e1", timestamp=1.0)
        new = self._make_entry("e2", timestamp=2.0)
        winner = self.enforcer.resolve_conflict(old, new, ConflictResolution.LAST_WRITE_WINS)
        self.assertEqual(winner.entry_id, "e2")

    def test_first_write_wins(self):
        old = self._make_entry("e1", timestamp=1.0)
        new = self._make_entry("e2", timestamp=2.0)
        winner = self.enforcer.resolve_conflict(old, new, ConflictResolution.FIRST_WRITE_WINS)
        self.assertEqual(winner.entry_id, "e1")

    def test_higher_priority_wins(self):
        low = self._make_entry("e1", memory_type="turn_raw")   # priority 10
        high = self._make_entry("e2", memory_type="correction") # priority 60
        winner = self.enforcer.resolve_conflict(low, high, ConflictResolution.HIGHER_PRIORITY_WINS)
        self.assertEqual(winner.entry_id, "e2")

    def test_higher_priority_existing_wins(self):
        high = self._make_entry("e1", memory_type="correction") # priority 60
        low = self._make_entry("e2", memory_type="turn_raw")    # priority 10
        winner = self.enforcer.resolve_conflict(high, low, ConflictResolution.HIGHER_PRIORITY_WINS)
        self.assertEqual(winner.entry_id, "e1")

    def test_equal_priority_favors_new(self):
        a = self._make_entry("e1", memory_type="turn_raw")
        b = self._make_entry("e2", memory_type="turn_raw")
        winner = self.enforcer.resolve_conflict(a, b, ConflictResolution.HIGHER_PRIORITY_WINS)
        self.assertEqual(winner.entry_id, "e2")

    def test_manual_review_defaults_to_new(self):
        old = self._make_entry("e1")
        new = self._make_entry("e2")
        winner = self.enforcer.resolve_conflict(old, new, ConflictResolution.MANUAL_REVIEW)
        self.assertEqual(winner.entry_id, "e2")

    def test_conflict_recorded_in_ledger(self):
        old = self._make_entry("e1")
        new = self._make_entry("e2")
        self.enforcer.resolve_conflict(old, new, ConflictResolution.LAST_WRITE_WINS)
        ledger = self.enforcer.get_ledger()
        conflict_entries = [e for e in ledger if e["operation"] == "conflict_resolved"]
        self.assertGreater(len(conflict_entries), 0)
        self.assertEqual(conflict_entries[-1]["conflict_resolution"], "last_write_wins")


class TestLedgerBehavior(unittest.TestCase):
    """Ledger is immutable, bounded, and filterable."""

    def setUp(self):
        self.enforcer = MemorySiloEnforcer()

    def test_write_creates_ledger_entry(self):
        self.enforcer.enforce_write(
            persona_id="default", memory_type="turn_raw",
            session_id="s1", user_id="u1", write_reason="turn_raw",
            correlation_id="req_abc",
        )
        ledger = self.enforcer.get_ledger()
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["operation"], "write")
        self.assertEqual(ledger[0]["correlation_id"], "req_abc")

    def test_ledger_bounded(self):
        enforcer = MemorySiloEnforcer()
        enforcer._max_ledger = 10
        for i in range(20):
            enforcer.enforce_write(
                persona_id="default", memory_type="turn_raw",
                session_id=f"s{i}", user_id="u1", write_reason="turn_raw",
            )
        self.assertLessEqual(len(enforcer._ledger), 10)

    def test_ledger_filter_by_persona(self):
        self.enforcer.register_silo(SiloPolicy(persona_id="sonia"))
        self.enforcer.enforce_write(
            persona_id="default", memory_type="turn_raw",
            session_id="s1", user_id="u1", write_reason="turn_raw",
        )
        self.enforcer.enforce_write(
            persona_id="sonia", memory_type="turn_summary",
            session_id="s2", user_id="u1", write_reason="turn_summary",
        )
        sonia_entries = self.enforcer.get_ledger(persona_id="sonia")
        default_entries = self.enforcer.get_ledger(persona_id="default")
        self.assertEqual(len(sonia_entries), 1)
        self.assertEqual(len(default_entries), 1)


class TestMemoryTypePriority(unittest.TestCase):
    """Priority ordering is correct and deterministic."""

    def test_correction_highest(self):
        self.assertEqual(max(MEMORY_TYPE_PRIORITY, key=MEMORY_TYPE_PRIORITY.get), "correction")

    def test_turn_raw_lowest(self):
        self.assertEqual(min(MEMORY_TYPE_PRIORITY, key=MEMORY_TYPE_PRIORITY.get), "turn_raw")

    def test_all_standard_types_present(self):
        expected = {"turn_raw", "turn_summary", "vision_observation", "tool_event",
                    "confirmation_event", "system_state", "user_fact", "correction"}
        self.assertEqual(set(MEMORY_TYPE_PRIORITY.keys()), expected)


if __name__ == "__main__":
    unittest.main()
