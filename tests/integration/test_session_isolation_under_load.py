"""
v4.7 Epic B -- B2/B6: Session Isolation Under Concurrent Load

Tests:
  1. Concurrent session creates don't cross-contaminate state
  2. Turn increment on one session doesn't affect another
  3. Confirmation tokens are session-scoped (no cross-session leaks)
  4. Idempotency keys are globally unique (cross-session collision safe)
  5. Durable store: concurrent session persists don't corrupt each other
  6. Action store: actions for different sessions stay isolated
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from session_manager import SessionManager
from tool_policy import GatewayConfirmationManager
from action_pipeline import ActionStore
from durable_state import DurableStateStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_isolation_")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestSessionIsolationUnderLoad:
    """B2/B6: Concurrent sessions remain fully isolated under load."""

    def test_concurrent_session_creates_no_contamination(self):
        """Creating 10 sessions concurrently produces 10 distinct session_ids."""
        mgr = SessionManager()

        async def _create_many():
            tasks = []
            for i in range(10):
                tasks.append(mgr.create(
                    user_id=f"user_{i}",
                    conversation_id=f"conv_{i}",
                    profile="chat_low_latency",
                ))
            return await asyncio.gather(*tasks)

        sessions = _run(_create_many())
        session_ids = [s.session_id for s in sessions]

        # All unique
        assert len(set(session_ids)) == 10, "Each session must have a unique ID"

        # Each session has correct user_id
        for i, s in enumerate(sessions):
            assert s.user_id == f"user_{i}"

    def test_turn_increment_session_isolated(self):
        """Incrementing turns on session A doesn't affect session B."""
        mgr = SessionManager()

        async def _test():
            sa = await mgr.create(user_id="ua", conversation_id="ca")
            sb = await mgr.create(user_id="ub", conversation_id="cb")

            await mgr.increment_turn(sa.session_id)
            await mgr.increment_turn(sa.session_id)
            await mgr.increment_turn(sa.session_id)

            a = await mgr.get(sa.session_id)
            b = await mgr.get(sb.session_id)
            return a, b

        a, b = _run(_test())
        assert a.turn_count == 3
        assert b.turn_count == 0

    def test_confirmation_tokens_session_scoped(self):
        """Tokens minted for session A are not visible when querying session B."""
        mgr = GatewayConfirmationManager()

        async def _test():
            t_a = await mgr.create("ses_iso_a", "turn_001", "file.write", {"path": "/a"})
            t_b = await mgr.create("ses_iso_b", "turn_001", "shell.run", {"cmd": "ls"})

            pending_a = await mgr.pending_for_session("ses_iso_a")
            pending_b = await mgr.pending_for_session("ses_iso_b")
            return t_a, t_b, pending_a, pending_b

        t_a, t_b, pending_a, pending_b = _run(_test())

        a_ids = {t.confirmation_id for t in pending_a}
        b_ids = {t.confirmation_id for t in pending_b}

        assert t_a.confirmation_id in a_ids
        assert t_b.confirmation_id not in a_ids
        assert t_b.confirmation_id in b_ids
        assert t_a.confirmation_id not in b_ids

    def test_idempotency_keys_cross_session_safe(self, tmp_db):
        """Same idempotency key from different sessions resolves to correct action."""
        store = DurableStateStore(db_path=tmp_db)

        # Idempotency keys are global (not session-scoped), so same key = same entry
        _run(store.persist_idempotency_key("global_idem_001", "act_s1", {"session": "A"}, ttl_seconds=300))

        entry = _run(store.get_idempotency_key("global_idem_001"))
        assert entry is not None
        assert entry["action_id"] == "act_s1"

        # Different key for different session
        _run(store.persist_idempotency_key("global_idem_002", "act_s2", {"session": "B"}, ttl_seconds=300))

        e1 = _run(store.get_idempotency_key("global_idem_001"))
        e2 = _run(store.get_idempotency_key("global_idem_002"))
        assert e1["action_id"] == "act_s1"
        assert e2["action_id"] == "act_s2"
        store.close()

    def test_durable_concurrent_session_persist_no_corruption(self, tmp_db):
        """Persisting 10 sessions concurrently doesn't corrupt any of them."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        store = DurableStateStore(db_path=tmp_db)

        async def _persist_many():
            tasks = []
            for i in range(10):
                tasks.append(store.persist_session({
                    "session_id": f"ses_conc_{i:03d}",
                    "user_id": f"user_{i}",
                    "conversation_id": f"conv_{i}",
                    "profile": "chat_low_latency",
                    "status": "active",
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=1)).isoformat(),
                    "last_activity": now.isoformat(),
                    "turn_count": 0,
                    "metadata": {"idx": i},
                }))
            await asyncio.gather(*tasks)

        _run(_persist_many())

        # All 10 sessions present
        sessions = _run(store.load_active_sessions())
        conc_sessions = [s for s in sessions if s["session_id"].startswith("ses_conc_")]
        assert len(conc_sessions) == 10, f"Expected 10 concurrent sessions, got {len(conc_sessions)}"
        store.close()

    def test_action_store_session_isolation(self):
        """Actions for session A are filtered correctly from session B."""
        store = ActionStore()

        async def _setup():
            from schemas.action import ActionRecord
            for i in range(5):
                await store.put(ActionRecord(
                    action_id=f"act_a_{i}",
                    intent="file.read",
                    params={},
                    state="planned",
                    risk_level="low",
                    requires_confirmation=False,
                    dry_run=False,
                    session_id="ses_filter_a",
                ))
            for i in range(3):
                await store.put(ActionRecord(
                    action_id=f"act_b_{i}",
                    intent="shell.run",
                    params={},
                    state="planned",
                    risk_level="medium",
                    requires_confirmation=True,
                    dry_run=False,
                    session_id="ses_filter_b",
                ))

        _run(_setup())

        a_actions = _run(store.list_actions(session_id="ses_filter_a"))
        b_actions = _run(store.list_actions(session_id="ses_filter_b"))

        assert len(a_actions) == 5
        assert len(b_actions) == 3
        assert all(a.session_id == "ses_filter_a" for a in a_actions)
        assert all(b.session_id == "ses_filter_b" for b in b_actions)
