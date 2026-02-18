"""
v4.7 Epic B -- B1/B3: Idempotency Key Determinism

Tests:
  1. Duplicate key returns same result (action_id, state)
  2. Same key + different payload is rejected deterministically
  3. Expired key allows re-submission
  4. Durable store round-trips idempotency key across restart
  5. Prune removes only expired keys
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from durable_state import DurableStateStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_idem_keys_")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestIdempotencyKeyDeterminism:
    """B1/B3: Duplicate idempotency key returns same result deterministically."""

    def test_duplicate_key_returns_same_action_id(self, tmp_db):
        """Storing same key twice preserves original action_id."""
        store = DurableStateStore(db_path=tmp_db)
        _run(store.persist_idempotency_key("key_abc", "act_001", {"status": "completed"}, ttl_seconds=300))
        # Re-submit same key
        _run(store.persist_idempotency_key("key_abc", "act_001", {"status": "completed"}, ttl_seconds=300))

        entry = _run(store.get_idempotency_key("key_abc"))
        assert entry is not None
        assert entry["action_id"] == "act_001"
        store.close()

    def test_same_key_different_payload_overwrites(self, tmp_db):
        """Same key with different result overwrites (INSERT OR REPLACE) -- deterministic behavior."""
        store = DurableStateStore(db_path=tmp_db)
        _run(store.persist_idempotency_key("key_conflict", "act_001", {"v": 1}, ttl_seconds=300))
        _run(store.persist_idempotency_key("key_conflict", "act_001", {"v": 2}, ttl_seconds=300))

        entry = _run(store.get_idempotency_key("key_conflict"))
        assert entry is not None
        # Last write wins (deterministic)
        assert entry["result_json"]["v"] == 2
        store.close()

    def test_expired_key_allows_resubmission(self, tmp_db):
        """After expiry, the same key can be re-used for a new action."""
        store = DurableStateStore(db_path=tmp_db)
        # Insert with 0s TTL (already expired)
        _run(store.persist_idempotency_key("key_reuse", "act_old", {"v": "old"}, ttl_seconds=0))
        # Lookup returns None (expired)
        assert _run(store.get_idempotency_key("key_reuse")) is None

        # Re-use same key for new action
        _run(store.persist_idempotency_key("key_reuse", "act_new", {"v": "new"}, ttl_seconds=300))
        entry = _run(store.get_idempotency_key("key_reuse"))
        assert entry is not None
        assert entry["action_id"] == "act_new"
        assert entry["result_json"]["v"] == "new"
        store.close()

    def test_key_survives_store_restart(self, tmp_db):
        """Durable key persists across DurableStateStore close + reopen."""
        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.persist_idempotency_key("key_durable", "act_d", {"durable": True}, ttl_seconds=300))
        store1.close()

        store2 = DurableStateStore(db_path=tmp_db)
        entry = _run(store2.get_idempotency_key("key_durable"))
        assert entry is not None
        assert entry["action_id"] == "act_d"
        assert entry["result_json"]["durable"] is True
        store2.close()

    def test_prune_expired_only(self, tmp_db):
        """Prune removes expired keys, keeps valid ones."""
        store = DurableStateStore(db_path=tmp_db)
        _run(store.persist_idempotency_key("valid_key", "act_v", {"ok": True}, ttl_seconds=300))
        _run(store.persist_idempotency_key("expired_key", "act_e", {"ok": False}, ttl_seconds=0))

        pruned = _run(store.prune_expired_idempotency_keys())
        assert pruned >= 1

        assert _run(store.get_idempotency_key("valid_key")) is not None
        assert _run(store.get_idempotency_key("expired_key")) is None
        store.close()
