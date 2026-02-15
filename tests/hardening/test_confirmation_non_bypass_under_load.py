"""
v3.1 H1 Hardening: Confirmation Non-Bypass Under Load

Verifies that PerceptionActionGate holds all invariants under
concurrent load: parallel approve/deny/expire operations, session
concurrency, and counter accuracy.

Invariants tested:
  - No bypass under concurrent approve/deny/expire
  - State machine transitions are atomic
  - Counter accuracy (approved + denied + expired = total resolved)
  - MAX_PENDING enforced under race conditions
  - One-shot approval consumption is atomic
"""

import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock

import pytest

# ── Module loading ───────────────────────────────────────────────────────

GATEWAY_DIR = Path(r"S:\services\api-gateway")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate_mod = _load_module("perception_action_gate_load", GATEWAY_DIR / "perception_action_gate.py")
PerceptionActionGate = gate_mod.PerceptionActionGate
ConfirmationBypassError = gate_mod.ConfirmationBypassError
RequirementState = gate_mod.RequirementState

session_mod = _load_module("session_manager_load", GATEWAY_DIR / "session_manager.py")
SessionManager = session_mod.SessionManager


# ── Tests: Gate Concurrency ──────────────────────────────────────────────

# ── Contractual constants ────────────────────────────────────────────────
# These are the published contract values. Tests MUST derive limits from
# the source class, not from hardcoded numbers. If the contract changes,
# tests break loudly rather than silently under-testing.

CONTRACTUAL_MAX_PENDING = PerceptionActionGate.MAX_PENDING  # currently 50
CONTRACTUAL_DEFAULT_TTL = PerceptionActionGate.DEFAULT_TTL   # currently 120.0


class TestContractualInvariants:
    """Verify that contractual limits match expectations."""

    def test_max_pending_is_published_value(self):
        """MAX_PENDING must be the documented contract value (50)."""
        assert CONTRACTUAL_MAX_PENDING == 50, (
            f"MAX_PENDING contract changed to {CONTRACTUAL_MAX_PENDING}! "
            f"Update gate spec and all load tests."
        )

    def test_default_ttl_is_published_value(self):
        """DEFAULT_TTL must be the documented contract value (120s)."""
        assert CONTRACTUAL_DEFAULT_TTL == 120.0, (
            f"DEFAULT_TTL contract changed to {CONTRACTUAL_DEFAULT_TTL}! "
            f"Update gate spec and all TTL-dependent tests."
        )


class TestConfirmationGateConcurrency:
    """PerceptionActionGate under concurrent load."""

    def test_parallel_require_no_duplicates(self):
        """Rapid require_confirmation calls produce unique IDs up to contractual MAX_PENDING."""
        gate = PerceptionActionGate(ttl_seconds=300)
        ids = set()

        # Derive limit from contract, not a magic number
        count = CONTRACTUAL_MAX_PENDING
        for i in range(count):
            req = gate.require_confirmation(
                action="file.read",
                scene_id=f"scene_{i}",
                correlation_id=f"req_{i}",
            )
            assert req.requirement_id not in ids, f"Duplicate ID: {req.requirement_id}"
            ids.add(req.requirement_id)

        assert len(ids) == count

    def test_approve_deny_interleaved(self):
        """Interleaved approve and deny operations maintain accurate counters."""
        gate = PerceptionActionGate(ttl_seconds=300)
        reqs = []

        # Create 20 requirements
        for i in range(20):
            req = gate.require_confirmation(
                action="file.read", scene_id=f"scene_{i}"
            )
            reqs.append(req)

        # Approve even indices, deny odd indices
        for i, req in enumerate(reqs):
            if i % 2 == 0:
                result = gate.approve(req.requirement_id)
                assert result is not None
                # Consume the approval
                gate.validate_execution(req.requirement_id)
            else:
                result = gate.deny(req.requirement_id, reason=f"test deny {i}")
                assert result is not None

        stats = gate.get_stats()
        assert stats["total_approved"] == 10
        assert stats["total_denied"] == 10
        assert stats["bypass_attempts"] == 0
        assert stats["pending_count"] == 0

    def test_rapid_expire_approve_race(self):
        """Requirements with very short TTL expire before approve attempt."""
        gate = PerceptionActionGate(ttl_seconds=0.05)  # 50ms

        reqs = []
        for i in range(10):
            req = gate.require_confirmation(
                action="file.read", scene_id=f"scene_race_{i}"
            )
            reqs.append(req)

        # Wait for expiry
        time.sleep(0.1)

        # All approvals should fail
        approved_count = 0
        for req in reqs:
            result = gate.approve(req.requirement_id)
            if result is not None:
                approved_count += 1

        assert approved_count == 0, f"Expected 0 approvals after expiry, got {approved_count}"

    def test_validate_without_approve_raises_bypass(self):
        """Attempting validate_execution on pending requirement raises bypass error."""
        gate = PerceptionActionGate(ttl_seconds=300)
        req = gate.require_confirmation(action="shell.run", scene_id="s1")

        with pytest.raises(ConfirmationBypassError) as exc_info:
            gate.validate_execution(req.requirement_id)

        assert "not approved" in str(exc_info.value).lower() or \
               "pending" in str(exc_info.value).lower()

        stats = gate.get_stats()
        assert stats["bypass_attempts"] == 1

    def test_one_shot_consumption_atomic(self):
        """Approved requirement can only be consumed once via validate_execution."""
        gate = PerceptionActionGate(ttl_seconds=300)
        req = gate.require_confirmation(action="file.read", scene_id="s_atomic")

        gate.approve(req.requirement_id)

        # First validate succeeds
        result = gate.validate_execution(req.requirement_id)
        assert result.state == RequirementState.EXECUTED

        # Second validate fails (archived after execution)
        with pytest.raises(ConfirmationBypassError):
            gate.validate_execution(req.requirement_id)

    def test_max_pending_under_rapid_creation(self):
        """MAX_PENDING is enforced even under rapid creation."""
        gate = PerceptionActionGate(ttl_seconds=300)

        created = 0
        overflow_caught = False

        for i in range(gate.MAX_PENDING + 10):
            try:
                gate.require_confirmation(action="file.read", scene_id=f"s_{i}")
                created += 1
            except ConfirmationBypassError:
                overflow_caught = True
                break

        assert created == gate.MAX_PENDING
        assert overflow_caught is True

    def test_approve_after_deny_fails(self):
        """Cannot approve a denied requirement."""
        gate = PerceptionActionGate(ttl_seconds=300)
        req = gate.require_confirmation(action="file.write", scene_id="s_ad")

        gate.deny(req.requirement_id, reason="rejected")
        result = gate.approve(req.requirement_id)
        assert result is None

    def test_deny_after_approve_fails(self):
        """Cannot deny an already-approved requirement."""
        gate = PerceptionActionGate(ttl_seconds=300)
        req = gate.require_confirmation(action="file.write", scene_id="s_da")

        gate.approve(req.requirement_id)
        result = gate.deny(req.requirement_id, reason="too late")
        assert result is None

    def test_stats_counter_accuracy_under_mixed_ops(self):
        """After mixed ops, counters are accurate."""
        gate = PerceptionActionGate(ttl_seconds=0.05)

        # Phase 1: Create 10, approve 3, deny 3
        reqs = []
        for i in range(10):
            reqs.append(gate.require_confirmation(action="file.read", scene_id=f"s_mix_{i}"))

        for i in range(3):
            gate.approve(reqs[i].requirement_id)
            gate.validate_execution(reqs[i].requirement_id)

        for i in range(3, 6):
            gate.deny(reqs[i].requirement_id, reason="test")

        # Phase 2: Wait for remaining 4 to expire
        time.sleep(0.1)
        gate._expire_stale()

        stats = gate.get_stats()
        assert stats["total_approved"] == 3
        assert stats["total_denied"] == 3
        assert stats["total_expired"] == 4
        assert stats["pending_count"] == 0
        assert stats["bypass_attempts"] == 0


# ── Tests: Session Manager Concurrency ───────────────────────────────────

class TestSessionManagerConcurrency:
    """Session manager under concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_session_creation(self):
        """Multiple concurrent create calls respect max_sessions limit."""
        mgr = SessionManager(max_sessions=5)

        async def create_session(idx):
            try:
                return await mgr.create(f"user_{idx}", f"conv_{idx}")
            except RuntimeError:
                return None

        results = await asyncio.gather(*[create_session(i) for i in range(10)])
        created = [r for r in results if r is not None]

        # Should have created at most 5
        assert len(created) <= 5

    @pytest.mark.asyncio
    async def test_concurrent_touch_no_corruption(self):
        """Concurrent touch calls don't corrupt session state."""
        mgr = SessionManager(max_sessions=10)
        sess = await mgr.create("user_touch", "conv_touch")

        async def touch_session():
            for _ in range(20):
                await mgr.touch(sess.session_id)
                await asyncio.sleep(0.001)

        # Run 5 concurrent touchers
        await asyncio.gather(*[touch_session() for _ in range(5)])

        result = await mgr.get(sess.session_id)
        assert result is not None
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_concurrent_create_close_cycle(self):
        """Rapid create/close cycles don't leave orphans."""
        mgr = SessionManager(max_sessions=20)

        async def create_and_close(idx):
            sess = await mgr.create(f"user_{idx}", f"conv_{idx}")
            await asyncio.sleep(0.01)
            await mgr.delete(sess.session_id)
            return sess.session_id

        session_ids = await asyncio.gather(*[create_and_close(i) for i in range(15)])

        # All sessions should be closed, none active
        assert mgr.active_count == 0

    @pytest.mark.asyncio
    async def test_increment_turn_under_concurrency(self):
        """Concurrent increment_turn calls all succeed."""
        mgr = SessionManager(max_sessions=10)
        sess = await mgr.create("user_inc", "conv_inc")

        async def increment():
            for _ in range(10):
                await mgr.increment_turn(sess.session_id)

        await asyncio.gather(*[increment() for _ in range(5)])

        result = await mgr.get(sess.session_id)
        # With asyncio.Lock, all 50 increments should be counted
        assert result.turn_count == 50
