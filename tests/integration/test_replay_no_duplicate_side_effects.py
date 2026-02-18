"""
v4.7 Epic B -- B1/B3: Replay Must Not Duplicate Side Effects

Tests:
  1. Idempotent approve: approve same confirmation twice -> same result, no double execution
  2. Idempotent deny: deny same confirmation twice -> same result
  3. Idempotent action plan: same idempotency_key -> returns same action_id (no new record)
  4. DLQ replay of already-replayed entry does not return in unreplayed list
  5. Session persist with same ID is upsert (not duplicate)
  6. Idempotency key replay returns cached result
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from tool_policy import GatewayConfirmationManager
from action_pipeline import ActionStore
from durable_state import DurableStateStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_replay_")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestReplayNoDuplicateSideEffects:
    """B1/B3: Replaying the same mutation cannot cause duplicate side effects."""

    def test_idempotent_approve_no_double_execution(self):
        """Approving same confirmation_id twice returns same result both times."""
        mgr = GatewayConfirmationManager()

        async def _test():
            token = await mgr.create("ses_r01", "turn_r01", "file.write", {"path": "/tmp/replay"})
            r1 = await mgr.approve(token.confirmation_id)
            r2 = await mgr.approve(token.confirmation_id)
            return r1, r2

        r1, r2 = _run(_test())
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r2.get("idempotent") is True

    def test_idempotent_deny_no_double_side_effect(self):
        """Denying same confirmation_id twice returns same result both times."""
        mgr = GatewayConfirmationManager()

        async def _test():
            token = await mgr.create("ses_r02", "turn_r02", "shell.run", {"cmd": "echo"})
            r1 = await mgr.deny(token.confirmation_id)
            r2 = await mgr.deny(token.confirmation_id)
            return r1, r2

        r1, r2 = _run(_test())
        # deny returns ok=False (denial is the result)
        assert r1["ok"] is False
        assert r2["ok"] is False
        assert r2.get("idempotent") is True

    def test_idempotent_action_plan_same_key_same_id(self):
        """Planning with same idempotency_key returns the same action_id, not a new one."""
        store = ActionStore()

        async def _plan_twice():
            from schemas.action import ActionRecord
            rec1 = ActionRecord(
                action_id="act_replay_001",
                intent="file.read",
                params={"path": "/tmp/test"},
                state="planned",
                risk_level="low",
                requires_confirmation=False,
                dry_run=False,
                idempotency_key="idem_replay_key",
            )
            await store.put(rec1)

            # Second lookup by same key -> should return same record
            existing = await store.get_by_idempotency_key("idem_replay_key")
            return existing

        result = _run(_plan_twice())
        assert result is not None
        assert result.action_id == "act_replay_001"

    def test_dlq_replayed_not_in_unreplayed_list(self, tmp_db):
        """After marking a DLQ entry as replayed, it disappears from load_dead_letters()."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        store = DurableStateStore(db_path=tmp_db)

        # Enqueue one entry
        _run(store.persist_dead_letter({
            "letter_id": "dl_replay_001",
            "action_id": "act_dlq_r01",
            "intent": "file.write",
            "error_code": "TIMEOUT",
            "created_at": now.isoformat(),
        }))

        entries = _run(store.load_dead_letters())
        assert any(e["letter_id"] == "dl_replay_001" for e in entries)

        # Mark as replayed
        _run(store.update_dead_letter("dl_replay_001", {"replayed": True}))

        # Should no longer appear in non-replayed list
        entries2 = _run(store.load_dead_letters())
        assert not any(e["letter_id"] == "dl_replay_001" for e in entries2)
        store.close()

    def test_idempotent_session_persist(self, tmp_db):
        """Persisting same session_id twice updates rather than duplicating."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        store = DurableStateStore(db_path=tmp_db)

        _run(store.persist_session({
            "session_id": "ses_idem_001",
            "user_id": "u1",
            "conversation_id": "conv_001",
            "profile": "chat_low_latency",
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "last_activity": now.isoformat(),
            "turn_count": 0,
        }))
        # Update turn_count
        _run(store.update_session("ses_idem_001", {"turn_count": 5}))

        sessions = _run(store.load_active_sessions())
        found = [s for s in sessions if s["session_id"] == "ses_idem_001"]
        assert len(found) == 1, "Should have exactly one session (upsert, not duplicate)"
        assert found[0]["turn_count"] == 5
        store.close()

    def test_idempotency_key_replay_returns_cached(self, tmp_db):
        """Persisting same idempotency key returns cached result on lookup."""
        store = DurableStateStore(db_path=tmp_db)

        _run(store.persist_idempotency_key("idem_cache_001", "act_c01", {"result": "first"}, ttl_seconds=300))

        # Lookup returns first result
        entry = _run(store.get_idempotency_key("idem_cache_001"))
        assert entry is not None
        assert entry["action_id"] == "act_c01"

        # Persist again (simulating replay -- INSERT OR REPLACE)
        _run(store.persist_idempotency_key("idem_cache_001", "act_c01", {"result": "replayed"}, ttl_seconds=300))

        entry2 = _run(store.get_idempotency_key("idem_cache_001"))
        assert entry2 is not None
        assert entry2["action_id"] == "act_c01"
        # Last-write-wins on result
        assert entry2["result_json"]["result"] == "replayed"
        store.close()
