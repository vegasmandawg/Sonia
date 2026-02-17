"""
v4.7 Epic B -- B5/B6: Deterministic Conflict Envelopes

Tests:
  1. Approve on non-existent confirmation returns deterministic error envelope
  2. Deny on non-existent confirmation returns deterministic error envelope
  3. Action state transition to invalid state returns no-op (safe)
  4. Approve on already-denied token returns idempotent deny envelope
  5. Deny on already-approved token returns idempotent approve envelope
  6. Error envelope has consistent shape (ok, status fields)
  7. Durable store: get non-existent key returns None (not exception)
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
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_conflict_")
    os.close(fd)
    yield path
    for ext in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + ext)
        except OSError:
            pass


class TestConflictEnvelopes:
    """B5/B6: Race conditions and retries produce deterministic error envelopes."""

    def test_approve_nonexistent_returns_error_envelope(self):
        """Approve on unknown confirmation_id returns {ok: False, ...}."""
        mgr = GatewayConfirmationManager()

        r = _run(mgr.approve("cfm_does_not_exist_999"))
        assert r["ok"] is False
        assert "status" in r

    def test_deny_nonexistent_returns_error_envelope(self):
        """Deny on unknown confirmation_id returns {ok: False, ...}."""
        mgr = GatewayConfirmationManager()

        r = _run(mgr.deny("cfm_does_not_exist_888"))
        assert r["ok"] is False
        assert "status" in r

    def test_action_store_update_nonexistent_is_safe(self):
        """Updating state on non-existent action_id does not raise."""
        store = ActionStore()
        # Should not raise -- just a no-op
        _run(store.update_state("act_nonexistent_999", "validated"))

        # Verify the action still doesn't exist
        rec = _run(store.get("act_nonexistent_999"))
        assert rec is None

    def test_approve_already_denied_returns_idempotent_deny(self):
        """Approve after deny returns {ok: False, idempotent: True}."""
        mgr = GatewayConfirmationManager()

        async def _test():
            token = await mgr.create("ses_c01", "turn_c01", "file.write", {"path": "/tmp/c"})
            await mgr.deny(token.confirmation_id)
            r = await mgr.approve(token.confirmation_id)
            return r

        r = _run(_test())
        assert r["ok"] is False
        assert r.get("idempotent") is True

    def test_deny_already_approved_returns_idempotent_approve(self):
        """Deny after approve returns {ok: False, idempotent: True}."""
        mgr = GatewayConfirmationManager()

        async def _test():
            token = await mgr.create("ses_c02", "turn_c02", "shell.run", {"cmd": "ls"})
            await mgr.approve(token.confirmation_id)
            r = await mgr.deny(token.confirmation_id)
            return r

        r = _run(_test())
        assert r["ok"] is False
        assert r.get("idempotent") is True

    def test_error_envelope_consistent_shape(self):
        """All error responses include 'ok' and 'status' fields consistently."""
        mgr = GatewayConfirmationManager()

        r1 = _run(mgr.approve("cfm_shape_001"))
        r2 = _run(mgr.deny("cfm_shape_002"))

        for r in [r1, r2]:
            assert "ok" in r
            assert isinstance(r["ok"], bool)
            assert r["ok"] is False
            assert "status" in r

    def test_durable_store_get_nonexistent_returns_none(self, tmp_db):
        """DurableStateStore returns None for missing keys, not exception."""
        store = DurableStateStore(db_path=tmp_db)

        # Sessions: load_active returns empty list (not exception)
        sessions = _run(store.load_active_sessions())
        assert isinstance(sessions, list)
        assert len(sessions) == 0

        # Confirmations: load_pending returns empty list
        pending = _run(store.load_pending_confirmations())
        assert isinstance(pending, list)
        assert len(pending) == 0

        # Idempotency key: returns None for missing key
        assert _run(store.get_idempotency_key("idem_never_existed")) is None
        store.close()
