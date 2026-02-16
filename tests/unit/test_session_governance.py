"""
v4.0 E1 Unit Tests -- Session & Memory Governance Hardening
============================================================
Tests for session_governance.py covering all 8 governance components:
1. Session quotas (5 tests)
2. Mutation authorization (5 tests)
3. Session kill-switch (3 tests)
4. Retention policy (5 tests)
5. Import/export safety (5 tests)
6. Incident snapshot (2 tests)
7. Turn sequencing (3 tests)
8. Redaction replay (4 tests)

Total: 32 tests (floor: 30)
"""

import hashlib
import json
import sys
import time

import pytest

sys.path.insert(0, r"S:\services\api-gateway")

from session_governance import (
    ExportValidationError,
    IncidentMemorySnapshot,
    KillSwitchResult,
    MemoryExportBundle,
    MemoryExportImportSafety,
    MutationAuthorizor,
    MutationDenied,
    MutationTier,
    RedactionAccessRecord,
    RedactionReplayTracker,
    RetentionEnforcer,
    RetentionPolicy,
    RETENTION_TTL,
    DEFAULT_RETENTION,
    SessionKillSwitch,
    SessionQuotaExceeded,
    SessionQuotaManager,
    TurnSequencer,
)


# ============================================================================
# 1. Session Quotas (5 tests)
# ============================================================================


class TestSessionQuotas:
    """Tests for per-user session quota enforcement."""

    def test_default_quota_allows_creation(self):
        """User with 0 sessions can create one."""
        mgr = SessionQuotaManager(default_limit=10)
        assert mgr.check_quota("user1", current_count=0) is True

    def test_quota_exceeded_raises(self):
        """User at limit is denied new sessions."""
        mgr = SessionQuotaManager(default_limit=3)
        with pytest.raises(SessionQuotaExceeded) as exc_info:
            mgr.check_quota("user1", current_count=3)
        assert exc_info.value.limit == 3
        assert exc_info.value.current == 3

    def test_custom_user_limit(self):
        """Per-user override takes precedence over default."""
        mgr = SessionQuotaManager(default_limit=5)
        mgr.set_user_limit("vip_user", 20)
        assert mgr.get_user_limit("vip_user") == 20
        assert mgr.get_user_limit("normal_user") == 5

    def test_session_tracking(self):
        """Track session create/close counts."""
        mgr = SessionQuotaManager(default_limit=10)
        assert mgr.track_session_created("user1") == 1
        assert mgr.track_session_created("user1") == 2
        assert mgr.track_session_closed("user1") == 1
        assert mgr.get_user_count("user1") == 1

    def test_stats(self):
        """Stats reflect current state."""
        mgr = SessionQuotaManager(default_limit=10)
        mgr.track_session_created("user1")
        mgr.track_session_created("user2")
        stats = mgr.get_stats()
        assert stats["total_active"] == 2
        assert stats["users_with_sessions"] == 2


# ============================================================================
# 2. Mutation Authorization (5 tests)
# ============================================================================


class TestMutationAuthorization:
    """Tests for session-level mutation tier enforcement."""

    def test_standard_allows_writes(self):
        """Standard tier permits memory writes."""
        auth = MutationAuthorizor()
        assert auth.check_memory_write("ses_001") is True

    def test_read_only_blocks_writes(self):
        """Read-only tier blocks memory writes."""
        auth = MutationAuthorizor()
        auth.set_session_tier("ses_001", MutationTier.READ_ONLY)
        with pytest.raises(MutationDenied) as exc_info:
            auth.check_memory_write("ses_001")
        assert exc_info.value.operation == "memory_write"

    def test_read_only_blocks_tool_execution(self):
        """Read-only tier blocks tool execution."""
        auth = MutationAuthorizor()
        auth.lock_session("ses_002")
        with pytest.raises(MutationDenied):
            auth.check_tool_execution("ses_002", "file.write")

    def test_lock_unlock_cycle(self):
        """Lock then unlock restores standard access."""
        auth = MutationAuthorizor()
        auth.lock_session("ses_003")
        assert auth.get_session_tier("ses_003") == MutationTier.READ_ONLY
        auth.unlock_session("ses_003")
        assert auth.get_session_tier("ses_003") == MutationTier.STANDARD
        assert auth.check_memory_write("ses_003") is True

    def test_denial_stats(self):
        """Stats track checks and denials."""
        auth = MutationAuthorizor()
        auth.lock_session("ses_004")
        try:
            auth.check_memory_write("ses_004")
        except MutationDenied:
            pass
        auth.check_memory_write("ses_005")  # default standard
        stats = auth.get_stats()
        assert stats["total_checks"] == 2
        assert stats["total_denials"] == 1


# ============================================================================
# 3. Session Kill-Switch (3 tests)
# ============================================================================


class TestSessionKillSwitch:
    """Tests for atomic session revocation."""

    def test_kill_switch_invokes_callback(self):
        """Kill-switch calls close callback for each session."""
        closed = []
        ks = SessionKillSwitch()
        result = ks.execute(
            user_id="user1",
            active_session_ids=["ses_a", "ses_b", "ses_c"],
            close_callback=lambda sid: closed.append(sid),
        )
        assert result.sessions_killed == 3
        assert set(closed) == {"ses_a", "ses_b", "ses_c"}

    def test_kill_switch_tolerates_callback_errors(self):
        """Kill-switch continues if one callback fails."""
        def flaky_close(sid):
            if sid == "ses_b":
                raise RuntimeError("simulated error")
        ks = SessionKillSwitch()
        result = ks.execute("user1", ["ses_a", "ses_b", "ses_c"], flaky_close)
        assert result.sessions_killed == 2  # ses_a and ses_c
        assert "ses_a" in result.session_ids
        assert "ses_b" not in result.session_ids

    def test_kill_log(self):
        """Kill-switch maintains an audit log."""
        ks = SessionKillSwitch()
        ks.execute("user1", ["ses_a"])
        ks.execute("user2", ["ses_x", "ses_y"])
        log = ks.get_kill_log()
        assert len(log) == 2
        assert log[1]["sessions_killed"] == 2


# ============================================================================
# 4. Retention Policy (5 tests)
# ============================================================================


class TestRetentionPolicy:
    """Tests for TTL-based memory retention enforcement."""

    def test_permanent_never_expires(self):
        """Permanent retention has no expiry."""
        enforcer = RetentionEnforcer()
        rec = enforcer.assign_retention("mem_001", "user_fact")
        assert rec.expires_at is None
        assert rec.is_expired is False

    def test_short_term_has_ttl(self):
        """Short-term retention has 24h TTL."""
        enforcer = RetentionEnforcer()
        rec = enforcer.assign_retention("mem_002", "turn_raw")
        assert rec.retention_policy == "short_term"
        assert rec.expires_at is not None
        # Should expire in ~24h from now
        assert rec.expires_at > time.time()
        assert rec.expires_at < time.time() + 86400 + 10

    def test_check_expired_empty(self):
        """No records -> no expired."""
        enforcer = RetentionEnforcer()
        enforcer.assign_retention("mem_003", "user_fact")  # permanent
        assert enforcer.check_expired() == []

    def test_ephemeral_expires_on_session_close(self):
        """Ephemeral memories expire when session closes."""
        enforcer = RetentionEnforcer()
        enforcer.assign_retention(
            "mem_004", "turn_raw", session_id="ses_001",
            policy_override="ephemeral",
        )
        expired = enforcer.expire_for_session("ses_001")
        assert "mem_004" in expired

    def test_default_retention_mappings(self):
        """All default retention types map to valid policies."""
        for mem_type, policy in DEFAULT_RETENTION.items():
            assert policy in RETENTION_TTL, f"No TTL for {policy}"


# ============================================================================
# 5. Import/Export Safety (5 tests)
# ============================================================================


class TestImportExportSafety:
    """Tests for memory import/export validation."""

    def test_export_produces_valid_bundle(self):
        """Export creates bundle with integrity hash."""
        safety = MemoryExportImportSafety()
        memories = [
            {"type": "user_fact", "content": "likes coffee", "metadata": {"user_id": "u1"}},
            {"type": "correction", "content": "prefers tea", "metadata": {"user_id": "u1"}},
        ]
        bundle = safety.validate_for_export(memories, user_id="u1")
        assert bundle.integrity_hash
        assert len(bundle.integrity_hash) == 64  # SHA-256
        assert bundle.user_id == "u1"
        assert len(bundle.memories) == 2

    def test_export_strips_forbidden_fields(self):
        """Export removes forbidden fields from memories."""
        safety = MemoryExportImportSafety()
        memories = [
            {"type": "fact", "content": "test", "password": "secret123", "metadata": {"user_id": "u1"}},
        ]
        bundle = safety.validate_for_export(memories, user_id="u1")
        assert "password" not in bundle.memories[0]

    def test_export_rejects_cross_user_memories(self):
        """Export rejects memories belonging to different user."""
        safety = MemoryExportImportSafety()
        memories = [
            {"type": "fact", "content": "test", "metadata": {"user_id": "u2"}},
        ]
        with pytest.raises(ExportValidationError, match="belongs to user u2"):
            safety.validate_for_export(memories, user_id="u1")

    def test_import_validates_integrity_hash(self):
        """Import rejects bundles with tampered integrity hash."""
        safety = MemoryExportImportSafety()
        bundle = {
            "format_version": "1.0",
            "user_id": "u1",
            "integrity_hash": "0000000000000000000000000000000000000000000000000000000000000000",
            "memories": [{"type": "fact", "content": "test"}],
        }
        with pytest.raises(ExportValidationError, match="Integrity hash mismatch"):
            safety.validate_for_import(bundle, target_user_id="u1")

    def test_import_rejects_wrong_user(self):
        """Import rejects bundles for wrong user."""
        safety = MemoryExportImportSafety()
        bundle = {"format_version": "1.0", "user_id": "u2", "memories": []}
        with pytest.raises(ExportValidationError, match="does not match"):
            safety.validate_for_import(bundle, target_user_id="u1")


# ============================================================================
# 6. Incident Snapshot (2 tests)
# ============================================================================


class TestIncidentSnapshot:
    """Tests for incident memory snapshot fields."""

    def test_snapshot_creation(self):
        """Snapshot captures all required fields."""
        snap = IncidentMemorySnapshot(
            incident_id="inc_001",
            timestamp=time.time(),
            session_id="ses_001",
            user_id="user1",
            correlation_id="req_abc",
            recent_memories=[{"id": "m1", "content": "test"}],
            active_sessions=["ses_001", "ses_002"],
            pending_mutations=[{"tool": "file.write", "status": "pending"}],
            retention_stats={"tracked": 10},
            silo_stats={"personas": 1},
            quota_stats={"total_active": 2},
        )
        d = snap.to_dict()
        assert d["incident_id"] == "inc_001"
        assert d["recent_memory_count"] == 1
        assert d["active_session_count"] == 2
        assert d["pending_mutation_count"] == 1

    def test_snapshot_serializable(self):
        """Snapshot dict is JSON-serializable."""
        snap = IncidentMemorySnapshot(
            incident_id="inc_002",
            timestamp=time.time(),
            session_id="ses_001",
            user_id="user1",
            correlation_id="req_xyz",
            recent_memories=[],
            active_sessions=[],
            pending_mutations=[],
            retention_stats={},
            silo_stats={},
            quota_stats={},
        )
        serialized = json.dumps(snap.to_dict())
        assert "inc_002" in serialized


# ============================================================================
# 7. Turn Sequencing (3 tests)
# ============================================================================


class TestTurnSequencing:
    """Tests for deterministic turn sequencing and rerun hashes."""

    def test_monotonic_sequence(self):
        """Turn numbers are monotonically increasing per session."""
        seq = TurnSequencer()
        assert seq.next_turn_num("ses_001") == 1
        assert seq.next_turn_num("ses_001") == 2
        assert seq.next_turn_num("ses_001") == 3
        assert seq.get_current("ses_001") == 3

    def test_sessions_independent(self):
        """Different sessions have independent counters."""
        seq = TurnSequencer()
        seq.next_turn_num("ses_a")
        seq.next_turn_num("ses_a")
        assert seq.next_turn_num("ses_b") == 1
        assert seq.next_turn_num("ses_a") == 3

    def test_rerun_hash_deterministic(self):
        """Same inputs always produce same hash."""
        seq = TurnSequencer()
        h1 = seq.compute_rerun_hash("ses_001", 1, "hello", "world")
        h2 = seq.compute_rerun_hash("ses_001", 1, "hello", "world")
        h3 = seq.compute_rerun_hash("ses_001", 2, "hello", "world")
        assert h1 == h2  # same input -> same hash
        assert h1 != h3  # different turn_num -> different hash


# ============================================================================
# 8. Redaction Replay (4 tests)
# ============================================================================


class TestRedactionReplay:
    """Tests for redaction access tracking and replay integrity."""

    def test_record_access(self):
        """Access to redacted content is tracked."""
        tracker = RedactionReplayTracker()
        record = tracker.record_access(
            session_id="ses_001",
            user_id="user1",
            memory_id="mem_001",
            access_type="query",
            redacted_fields=["ssn", "email"],
        )
        assert record.access_id == "ra_000001"
        assert len(record.redacted_fields) == 2

    def test_access_log_filtered(self):
        """Access log can be filtered by user and session."""
        tracker = RedactionReplayTracker()
        tracker.record_access("ses_001", "user1", "mem_001", "query", ["ssn"])
        tracker.record_access("ses_002", "user2", "mem_002", "retrieve", ["email"])
        tracker.record_access("ses_001", "user1", "mem_003", "export", ["phone"])

        user1_log = tracker.get_access_log(user_id="user1")
        assert len(user1_log) == 2

        ses1_log = tracker.get_access_log(session_id="ses_001")
        assert len(ses1_log) == 2

    def test_replay_integrity_verification(self):
        """Replay integrity check detects missing records."""
        tracker = RedactionReplayTracker()
        r1 = tracker.record_access("ses_001", "u1", "m1", "query", ["f1"])
        r2 = tracker.record_access("ses_001", "u1", "m2", "query", ["f2"])

        result = tracker.verify_replay_integrity([r1.access_id, r2.access_id])
        assert result["integrity_ok"] is True
        assert result["found"] == 2

        # Check with non-existent ID
        result = tracker.verify_replay_integrity(["ra_999999"])
        assert result["integrity_ok"] is False
        assert result["missing"] == 1

    def test_bounded_records(self):
        """Record buffer is bounded to max_records."""
        tracker = RedactionReplayTracker(max_records=5)
        for i in range(10):
            tracker.record_access("ses", "u", f"m{i}", "query", [])
        assert len(tracker._records) == 5
        stats = tracker.get_stats()
        assert stats["total_records"] == 5
        assert stats["counter"] == 10
