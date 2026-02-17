"""
v4.7 Epic B — B4: Durable Idempotency Store Tests

Validates that:
1. IdempotencyStore class/table exists in DurableStateStore
2. Keys persist across store re-instantiation (simulated restart)
3. Expired keys are pruned and not returned
4. Duplicate key returns cached result (same action_id)
5. Result payload round-trips correctly
6. Prune removes only expired entries
7. Non-existent key returns None
"""

import asyncio
import json
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from durable_state import DurableStateStore


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_idemp_")
    os.close(fd)
    yield path
    # Cleanup
    for ext in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + ext)
        except OSError:
            pass


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestIdempotencyStoreDurable:
    """B4: Durable idempotency store survives restart."""

    def test_idempotency_table_exists(self, tmp_db):
        """idempotency_keys table is created on init."""
        store = DurableStateStore(db_path=tmp_db)
        cur = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency_keys'"
        )
        assert cur.fetchone() is not None, "idempotency_keys table must exist"
        store.close()

    def test_key_persists_across_restart(self, tmp_db):
        """Idempotency key survives store close + re-open."""
        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.persist_idempotency_key(
            key="idem_abc123",
            action_id="act_001",
            result={"status": "completed", "output": "ok"},
            ttl_seconds=300.0,
        ))
        store1.close()

        # Re-open (simulated restart)
        store2 = DurableStateStore(db_path=tmp_db)
        entry = _run(store2.get_idempotency_key("idem_abc123"))
        assert entry is not None, "Key must survive restart"
        assert entry["action_id"] == "act_001"
        store2.close()

    def test_expired_key_not_returned(self, tmp_db):
        """Expired keys return None on lookup."""
        store = DurableStateStore(db_path=tmp_db)
        # Insert with 0-second TTL (already expired)
        _run(store.persist_idempotency_key(
            key="idem_expired",
            action_id="act_002",
            result={"status": "done"},
            ttl_seconds=0.0,
        ))
        # Should not be found (expired)
        entry = _run(store.get_idempotency_key("idem_expired"))
        assert entry is None, "Expired key must return None"
        store.close()

    def test_duplicate_key_returns_same_result(self, tmp_db):
        """Writing same key twice updates result; lookup returns latest."""
        store = DurableStateStore(db_path=tmp_db)
        _run(store.persist_idempotency_key(
            key="idem_dup",
            action_id="act_003",
            result={"attempt": 1},
            ttl_seconds=300.0,
        ))
        _run(store.persist_idempotency_key(
            key="idem_dup",
            action_id="act_003",
            result={"attempt": 2},
            ttl_seconds=300.0,
        ))
        entry = _run(store.get_idempotency_key("idem_dup"))
        assert entry is not None
        assert entry["action_id"] == "act_003"
        assert entry["result_json"]["attempt"] == 2
        store.close()

    def test_result_payload_roundtrip(self, tmp_db):
        """Complex result payload round-trips through JSON."""
        store = DurableStateStore(db_path=tmp_db)
        payload = {
            "status": "completed",
            "output": {"files": ["a.txt", "b.txt"], "count": 2},
            "metadata": {"tier": "guarded_low"},
        }
        _run(store.persist_idempotency_key(
            key="idem_complex",
            action_id="act_004",
            result=payload,
            ttl_seconds=300.0,
        ))
        entry = _run(store.get_idempotency_key("idem_complex"))
        assert entry is not None
        assert entry["result_json"] == payload
        store.close()

    def test_prune_removes_only_expired(self, tmp_db):
        """Prune deletes expired entries, keeps valid ones."""
        store = DurableStateStore(db_path=tmp_db)
        # Insert one valid, one expired
        _run(store.persist_idempotency_key("idem_valid", "act_v", {"ok": True}, ttl_seconds=300.0))
        _run(store.persist_idempotency_key("idem_old", "act_o", {"ok": False}, ttl_seconds=0.0))

        pruned = _run(store.prune_expired_idempotency_keys())
        assert pruned >= 1, "At least one expired key should be pruned"

        # Valid key still exists
        assert _run(store.get_idempotency_key("idem_valid")) is not None
        # Expired key gone
        assert _run(store.get_idempotency_key("idem_old")) is None
        store.close()

    def test_nonexistent_key_returns_none(self, tmp_db):
        """Looking up a key that was never stored returns None."""
        store = DurableStateStore(db_path=tmp_db)
        entry = _run(store.get_idempotency_key("idem_never_existed"))
        assert entry is None
        store.close()
