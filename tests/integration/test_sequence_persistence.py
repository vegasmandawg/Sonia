"""
v4.7 Epic B -- B4/B6: Sequence Persistence Across Restart

Tests:
  1. DurableStateStore sessions table survives close + reopen
  2. Confirmation tokens persisted via write-through survive restart
  3. DLQ entries survive restart
  4. Outbox entries survive restart
  5. Restart budget store survives supervisor restart (eva-os)
  6. Multiple tables populated -> close -> reopen -> all present
"""

import asyncio
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from durable_state import DurableStateStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_seq_persist_")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestSequencePersistence:
    """B4/B6: Mutation sequences survive DurableStateStore restart."""

    def test_session_survives_restart(self, tmp_db):
        """Session written to durable store persists across close+reopen."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.persist_session({
            "session_id": "ses_persist_001",
            "user_id": "u1",
            "conversation_id": "conv_001",
            "profile": "chat_low_latency",
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "last_activity": now.isoformat(),
            "turn_count": 0,
            "metadata": {},
        }))
        store1.close()

        store2 = DurableStateStore(db_path=tmp_db)
        sessions = _run(store2.load_active_sessions())
        found = [s for s in sessions if s["session_id"] == "ses_persist_001"]
        assert len(found) == 1, "Session must survive restart"
        assert found[0]["user_id"] == "u1"
        store2.close()

    def test_confirmation_survives_restart(self, tmp_db):
        """Confirmation token written via write-through persists across restart."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.persist_confirmation({
            "confirmation_id": "cfm_persist_001",
            "session_id": "ses_001",
            "turn_id": "turn_001",
            "tool_name": "file.write",
            "args": {"path": "/tmp/test"},
            "summary": "file.write | path=/tmp/test",
            "status": "pending",
            "created_at": now.isoformat(),
            "ttl_seconds": 120.0,
            "decided_at": None,
        }))
        store1.close()

        store2 = DurableStateStore(db_path=tmp_db)
        pending = _run(store2.load_pending_confirmations())
        found = [c for c in pending if c["confirmation_id"] == "cfm_persist_001"]
        assert len(found) == 1, "Confirmation must survive restart"
        assert found[0]["tool_name"] == "file.write"
        store2.close()

    def test_dlq_survives_restart(self, tmp_db):
        """Dead letter entry persists across restart."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.persist_dead_letter({
            "letter_id": "dl_persist_001",
            "action_id": "act_dlq_001",
            "intent": "file.write",
            "params": {"path": "/tmp"},
            "error_code": "TIMEOUT",
            "error_message": "timed out",
            "failure_class": "TIMEOUT",
            "correlation_id": "req_001",
            "session_id": "ses_001",
            "created_at": now.isoformat(),
            "retries_exhausted": 1,
        }))
        store1.close()

        store2 = DurableStateStore(db_path=tmp_db)
        entries = _run(store2.load_dead_letters())
        found = [e for e in entries if e.get("action_id") == "act_dlq_001"]
        assert len(found) >= 1, "DLQ entry must survive restart"
        store2.close()

    def test_outbox_survives_restart(self, tmp_db):
        """Outbox entry persists across restart."""
        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.enqueue_outbox(
            entry_type="memory_write",
            payload={"session_id": "ses_out_001", "content": "test memory"},
        ))
        store1.close()

        store2 = DurableStateStore(db_path=tmp_db)
        entries = _run(store2.get_pending_outbox())
        assert len(entries) >= 1, "Outbox entry must survive restart"
        store2.close()

    def test_restart_budget_survives_restart(self):
        """RestartBudgetStore data persists across close+reopen."""
        sys.path.insert(0, r"S:\services\eva-os")
        from service_supervisor import RestartBudgetStore

        fd, path = tempfile.mkstemp(suffix=".db", prefix="test_budget_")
        os.close(fd)
        try:
            budget1 = RestartBudgetStore(db_path=path)
            budget1.record_attempt("api-gateway", time.time())
            budget1.close()

            budget2 = RestartBudgetStore(db_path=path)
            info = budget2.get_budget("api-gateway")
            assert info is not None, "Budget record must survive restart"
            assert info["attempt_count"] >= 1
            budget2.close()
        finally:
            for ext in ["", "-wal", "-shm"]:
                try:
                    os.unlink(path + ext)
                except OSError:
                    pass

    def test_multi_table_persistence(self, tmp_db):
        """Populate session + confirmation + idempotency -> restart -> all present."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        store1 = DurableStateStore(db_path=tmp_db)
        _run(store1.persist_session({
            "session_id": "ses_multi_001",
            "user_id": "u_multi",
            "conversation_id": "conv_multi",
            "profile": "chat_low_latency",
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "last_activity": now.isoformat(),
            "turn_count": 0,
        }))
        _run(store1.persist_confirmation({
            "confirmation_id": "cfm_multi_001",
            "session_id": "ses_multi_001",
            "turn_id": "turn_multi_001",
            "tool_name": "shell.run",
            "args": {},
            "summary": "shell.run",
            "status": "pending",
            "created_at": now.isoformat(),
            "ttl_seconds": 120.0,
        }))
        _run(store1.persist_idempotency_key("idem_multi_001", "act_m1", {"ok": True}, ttl_seconds=300))
        store1.close()

        store2 = DurableStateStore(db_path=tmp_db)
        sessions = _run(store2.load_active_sessions())
        assert any(s["session_id"] == "ses_multi_001" for s in sessions)
        pending = _run(store2.load_pending_confirmations())
        assert any(c["confirmation_id"] == "cfm_multi_001" for c in pending)
        assert _run(store2.get_idempotency_key("idem_multi_001")) is not None
        store2.close()
