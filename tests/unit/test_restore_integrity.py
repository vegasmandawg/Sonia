"""
Restore integrity tests for v3.6 P2.

Proves:
  1. Backup creates manifest with SHA-256 checksums.
  2. Verify passes on intact backup, fails on corrupted.
  3. DLQ restore dry_run=True does not mutate state.
  4. DLQ restore dry_run=False enqueues records.
  5. Missing backup returns error.
"""
import importlib.util, json, os, sys, tempfile, asyncio, unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# ── Load state_backup module ─────────────────────────────────────────────────
_GW = r"S:\services\api-gateway"
spec = importlib.util.spec_from_file_location("state_backup", os.path.join(_GW, "state_backup.py"))
sb_mod = importlib.util.module_from_spec(spec)
sys.modules["state_backup"] = sb_mod
spec.loader.exec_module(sb_mod)
StateBackupManager = sb_mod.StateBackupManager


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeDLQ:
    def __init__(self):
        self._records = []

    async def list_letters(self, limit=100, include_replayed=False):
        return self._records

    async def enqueue(self, **kwargs):
        self._records.append(kwargs)

    async def count(self, include_replayed=False):
        return len(self._records)


class FakeLetter:
    def __init__(self, intent, params):
        self.intent = intent
        self.params = params

    def to_dict(self):
        return {
            "action_id": "a1", "intent": self.intent, "params": self.params,
            "error_code": "TEST", "error_message": "test error",
            "correlation_id": "corr_1", "session_id": "s1",
            "retries_exhausted": 0, "failure_class": "TEST",
        }


class FakeActionStore:
    async def list_actions(self, limit=10000):
        return []


class FakeBreakerRegistry:
    def summary(self):
        return [{"name": "test_breaker", "state": "CLOSED"}]

    def metrics(self, last_n=200):
        return []


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBackupCreation(unittest.TestCase):
    """Backup must produce manifest with checksums."""

    def test_creates_manifest_with_checksums(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = StateBackupManager(backup_dir=Path(td))
            dlq = FakeDLQ()
            dlq._records = [FakeLetter("test.action", {"key": "val"})]
            store = FakeActionStore()
            breakers = FakeBreakerRegistry()

            manifest = _run(mgr.create_backup(dlq, store, breakers, label="test"))

            self.assertIn("backup_id", manifest)
            self.assertIn("checksums", manifest)
            self.assertIn("dead_letters.json", manifest["checksums"])
            self.assertEqual(len(manifest["checksums"]["dead_letters.json"]), 64)

    def test_manifest_contains_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = StateBackupManager(backup_dir=Path(td))
            manifest = _run(mgr.create_backup(FakeDLQ(), FakeActionStore(), FakeBreakerRegistry()))
            self.assertIn("artifacts", manifest)
            self.assertIn("dead_letters", manifest["artifacts"])


class TestBackupVerification(unittest.TestCase):
    """Verify must pass on intact, fail on corrupted."""

    def _create_backup(self, td):
        mgr = StateBackupManager(backup_dir=Path(td))
        dlq = FakeDLQ()
        dlq._records = [FakeLetter("a", {"b": "c"})]
        manifest = _run(mgr.create_backup(dlq, FakeActionStore(), FakeBreakerRegistry()))
        return mgr, manifest

    def test_verify_intact_passes(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, manifest = self._create_backup(td)
            result = _run(mgr.verify_backup(manifest["backup_id"]))
            self.assertTrue(result["ok"])

    def test_verify_corrupted_fails(self):
        with tempfile.TemporaryDirectory() as td:
            mgr, manifest = self._create_backup(td)
            # Corrupt dead_letters.json
            dl_path = Path(td) / manifest["backup_id"] / "dead_letters.json"
            dl_path.write_text("CORRUPTED DATA", encoding="utf-8")
            result = _run(mgr.verify_backup(manifest["backup_id"]))
            self.assertFalse(result["ok"])

    def test_verify_missing_backup(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = StateBackupManager(backup_dir=Path(td))
            result = _run(mgr.verify_backup("nonexistent-backup"))
            self.assertFalse(result["ok"])


class TestDLQRestore(unittest.TestCase):
    """DLQ restore dry_run vs real."""

    def test_dry_run_no_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = StateBackupManager(backup_dir=Path(td))
            dlq = FakeDLQ()
            dlq._records = [FakeLetter("x", {})]
            manifest = _run(mgr.create_backup(dlq, FakeActionStore(), FakeBreakerRegistry()))

            target_dlq = FakeDLQ()
            result = _run(mgr.restore_dlq(manifest["backup_id"], target_dlq, dry_run=True))
            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])
            self.assertEqual(len(target_dlq._records), 0)  # no mutation

    def test_real_restore_enqueues(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = StateBackupManager(backup_dir=Path(td))
            dlq = FakeDLQ()
            dlq._records = [FakeLetter("x", {"p": 1}), FakeLetter("y", {"q": 2})]
            manifest = _run(mgr.create_backup(dlq, FakeActionStore(), FakeBreakerRegistry()))

            target_dlq = FakeDLQ()
            result = _run(mgr.restore_dlq(manifest["backup_id"], target_dlq, dry_run=False))
            self.assertTrue(result["ok"])
            self.assertFalse(result["dry_run"])
            self.assertEqual(result["records_restored"], 2)
            self.assertEqual(len(target_dlq._records), 2)


class TestListBackups(unittest.TestCase):
    def test_lists_created_backups(self):
        with tempfile.TemporaryDirectory() as td:
            mgr = StateBackupManager(backup_dir=Path(td))
            _run(mgr.create_backup(FakeDLQ(), FakeActionStore(), FakeBreakerRegistry(), label="b1"))
            backups = mgr.list_backups()
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0]["label"], "b1")


if __name__ == "__main__":
    unittest.main()
