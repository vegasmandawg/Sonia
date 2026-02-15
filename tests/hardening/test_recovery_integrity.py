"""
v3.1 H1 Hardening: Crash-Recovery Integrity Tests

Verifies that after simulated crash (mid-operation), restarting
produces consistent state with no orphaned sessions, no phantom
confirmations, and intact provenance chains.

Invariants tested:
  - Session GC removes expired/idle sessions on next access
  - PerceptionActionGate expires stale confirmations (no phantom approvals)
  - ProvenanceTracker rejects empty required fields (no corrupt records)
  - Session restore from persistence filters out expired sessions
  - Confirmation state machine does not allow invalid transitions after restart
"""

import asyncio
import importlib.util
import json
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Module loading ───────────────────────────────────────────────────────

GATEWAY_DIR = Path(r"S:\services\api-gateway")
SHARED_DIR = Path(r"S:\services\shared")
MEMORY_DIR = Path(r"S:\services\memory-engine")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


session_mod = _load_module("session_manager", GATEWAY_DIR / "session_manager.py")
SessionManager = session_mod.SessionManager
Session = session_mod.Session

gate_mod = _load_module("perception_action_gate_ri", GATEWAY_DIR / "perception_action_gate.py")
PerceptionActionGate = gate_mod.PerceptionActionGate
ConfirmationBypassError = gate_mod.ConfirmationBypassError
RequirementState = gate_mod.RequirementState


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_expired_session_record(session_id: str) -> Dict[str, Any]:
    """Build a session record that is already expired."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=2)
    return {
        "session_id": session_id,
        "user_id": "user_test",
        "conversation_id": "conv_test",
        "profile": "chat_low_latency",
        "status": "active",
        "created_at": past.isoformat(),
        "expires_at": (past + timedelta(minutes=30)).isoformat(),  # expired
        "last_activity": past.isoformat(),
        "turn_count": 5,
        "metadata": {},
    }


def _make_active_session_record(session_id: str) -> Dict[str, Any]:
    """Build a session record that is still active."""
    now = datetime.now(timezone.utc)
    return {
        "session_id": session_id,
        "user_id": "user_test",
        "conversation_id": "conv_test",
        "profile": "chat_low_latency",
        "status": "active",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=30)).isoformat(),
        "last_activity": now.isoformat(),
        "turn_count": 0,
        "metadata": {},
    }


# ── Tests: Session Recovery ──────────────────────────────────────────────

class TestSessionRecoveryIntegrity:
    """Session manager recovery after simulated crash."""

    @pytest.mark.asyncio
    async def test_restore_filters_expired_sessions(self):
        """Expired sessions are NOT restored after restart."""
        mock_client = AsyncMock()
        mock_client.load_active_sessions = AsyncMock(return_value=[
            _make_expired_session_record("ses_expired_001"),
            _make_expired_session_record("ses_expired_002"),
            _make_active_session_record("ses_alive_001"),
        ])

        mgr = SessionManager(memory_client=mock_client)
        count = await mgr.restore_sessions()

        # Only the active session should be restored
        assert count == 1
        assert mgr.active_count <= 1

    @pytest.mark.asyncio
    async def test_restore_handles_persistence_failure(self):
        """If persistence backend is down, restore returns 0 gracefully."""
        mock_client = AsyncMock()
        mock_client.load_active_sessions = AsyncMock(side_effect=ConnectionError("DB down"))

        mgr = SessionManager(memory_client=mock_client)
        count = await mgr.restore_sessions()
        assert count == 0  # Graceful degradation

    @pytest.mark.asyncio
    async def test_no_orphaned_sessions_after_gc(self):
        """Creating sessions then simulating time passage GCs expired ones."""
        mgr = SessionManager(max_sessions=10, default_ttl=1)  # 1s TTL

        # Create sessions
        sess1 = await mgr.create("u1", "c1")
        sess2 = await mgr.create("u2", "c2")

        # Wait for TTL
        await asyncio.sleep(1.5)

        # Access should mark them expired
        s1 = await mgr.get(sess1.session_id)
        s2 = await mgr.get(sess2.session_id)

        assert s1.status == "expired"
        assert s2.status == "expired"

    @pytest.mark.asyncio
    async def test_close_then_restore_not_active(self):
        """Closed sessions are not counted as active."""
        mgr = SessionManager(max_sessions=10)
        sess = await mgr.create("u1", "c1")
        await mgr.delete(sess.session_id)

        closed = await mgr.get(sess.session_id)
        assert closed.status == "closed"
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_session_touch_updates_activity(self):
        """Touching a session updates last_activity timestamp."""
        mgr = SessionManager(max_sessions=10)
        sess = await mgr.create("u1", "c1")
        old_activity = sess.last_activity

        await asyncio.sleep(0.1)
        await mgr.touch(sess.session_id)

        updated = await mgr.get(sess.session_id)
        assert updated.last_activity >= old_activity


# ── Tests: Confirmation Gate Recovery ────────────────────────────────────

class TestConfirmationGateRecovery:
    """PerceptionActionGate state integrity after simulated restart."""

    def test_expired_confirmations_not_approvable(self):
        """After TTL passes, pending confirmations cannot be approved."""
        gate = PerceptionActionGate(ttl_seconds=0.1)  # 100ms TTL

        req = gate.require_confirmation(
            action="shell.run",
            args={"command": "ls"},
            scene_id="scene_crash",
        )

        # Wait for expiry
        time.sleep(0.2)

        # Approve should fail (expired)
        result = gate.approve(req.requirement_id)
        assert result is None

        # Validate execution should raise bypass error
        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution(req.requirement_id)

    def test_no_phantom_approvals_in_fresh_gate(self):
        """A fresh gate has no lingering approvals from before."""
        gate = PerceptionActionGate()
        stats = gate.get_stats()

        assert stats["pending_count"] == 0
        assert stats["total_approved"] == 0
        assert stats["total_denied"] == 0
        assert stats["bypass_attempts"] == 0

    def test_denied_cannot_be_approved(self):
        """Once denied, a requirement cannot be approved."""
        gate = PerceptionActionGate(ttl_seconds=300)
        req = gate.require_confirmation(action="file.write", scene_id="s1")

        gate.deny(req.requirement_id, reason="test denial")

        # Try to approve after denial
        result = gate.approve(req.requirement_id)
        assert result is None  # Cannot transition from denied to approved

    def test_executed_cannot_be_replayed(self):
        """Executed confirmations are archived and cannot be re-executed."""
        gate = PerceptionActionGate(ttl_seconds=300)
        req = gate.require_confirmation(action="file.read", scene_id="s2")

        gate.approve(req.requirement_id)
        gate.validate_execution(req.requirement_id)

        # Try to validate again (should fail, archived)
        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution(req.requirement_id)

    def test_bypass_counter_tracks_attempts(self):
        """Bypass attempts are counted accurately."""
        gate = PerceptionActionGate(ttl_seconds=300)

        # Try to validate a non-existent requirement
        for i in range(5):
            with pytest.raises(ConfirmationBypassError):
                gate.validate_execution(f"fake_req_{i}")

        stats = gate.get_stats()
        assert stats["bypass_attempts"] == 5

    def test_max_pending_enforced_on_recovery(self):
        """MAX_PENDING limit holds even after many creates."""
        gate = PerceptionActionGate(ttl_seconds=300)

        # Fill up to MAX_PENDING
        for i in range(gate.MAX_PENDING):
            gate.require_confirmation(action="file.read", scene_id=f"s_{i}")

        # Next one should raise
        with pytest.raises(ConfirmationBypassError) as exc_info:
            gate.require_confirmation(action="file.read", scene_id="s_overflow")

        assert "Max pending" in str(exc_info.value)


# ── Tests: Provenance Recovery ───────────────────────────────────────────

class TestProvenanceRecoveryIntegrity:
    """Provenance tracker rejects invalid data (no corrupt records on recovery)."""

    def test_perception_provenance_rejects_empty_scene_id(self):
        """track_perception raises ValueError for empty scene_id."""
        # We need a mock DB for ProvenanceTracker
        mock_db = MagicMock()
        mock_db.connection = MagicMock(return_value=MagicMock(
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        ))

        prov_mod = _load_module("provenance_ri", MEMORY_DIR / "core" / "provenance.py")
        tracker = prov_mod.ProvenanceTracker(mock_db)

        with pytest.raises(ValueError, match="scene_id"):
            tracker.track_perception(
                memory_id="mem_test",
                scene_id="",  # empty
                correlation_id="req_abc",
                trigger="test",
                model_used="model_v1",
            )

    def test_perception_provenance_rejects_empty_correlation(self):
        """track_perception raises ValueError for empty correlation_id."""
        mock_db = MagicMock()
        prov_mod = _load_module("provenance_ri2", MEMORY_DIR / "core" / "provenance.py")
        tracker = prov_mod.ProvenanceTracker(mock_db)

        with pytest.raises(ValueError, match="correlation_id"):
            tracker.track_perception(
                memory_id="mem_test",
                scene_id="scene_001",
                correlation_id="",  # empty
                trigger="test",
                model_used="model_v1",
            )

    def test_perception_provenance_rejects_empty_trigger(self):
        """track_perception raises ValueError for empty trigger."""
        mock_db = MagicMock()
        prov_mod = _load_module("provenance_ri3", MEMORY_DIR / "core" / "provenance.py")
        tracker = prov_mod.ProvenanceTracker(mock_db)

        with pytest.raises(ValueError, match="trigger"):
            tracker.track_perception(
                memory_id="mem_test",
                scene_id="scene_001",
                correlation_id="req_abc",
                trigger="",  # empty
                model_used="model_v1",
            )

    def test_perception_provenance_rejects_empty_model(self):
        """track_perception raises ValueError for empty model_used."""
        mock_db = MagicMock()
        prov_mod = _load_module("provenance_ri4", MEMORY_DIR / "core" / "provenance.py")
        tracker = prov_mod.ProvenanceTracker(mock_db)

        with pytest.raises(ValueError, match="model_used"):
            tracker.track_perception(
                memory_id="mem_test",
                scene_id="scene_001",
                correlation_id="req_abc",
                trigger="test",
                model_used="",  # empty
            )
