"""Tests for session_boundary.py — v4.2 E1."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from session_boundary import SessionRecord, SessionBoundaryPolicy, AccessType


class TestSessionRecord:
    def test_valid_session(self):
        s = SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z")
        assert s.session_id == "s1"
        assert s.fingerprint  # non-empty

    def test_empty_session_id_rejected(self):
        with pytest.raises(ValueError, match="session_id"):
            SessionRecord("", "p1", "ns1", "2026-01-01T00:00:00Z")

    def test_fingerprint_deterministic(self):
        s1 = SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z")
        s2 = SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z")
        assert s1.fingerprint == s2.fingerprint


class TestSessionBoundaryPolicy:
    def test_same_session_access_allowed(self):
        policy = SessionBoundaryPolicy()
        s = SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z")
        policy.register_session(s)
        assert policy.check_access("s1", "s1", AccessType.READ) is True

    def test_cross_session_read_denied(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        policy.register_session(SessionRecord("s2", "p1", "ns2", "2026-01-01T00:00:00Z"))
        assert policy.check_access("s1", "s2", AccessType.READ) is False

    def test_cross_session_write_denied(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        policy.register_session(SessionRecord("s2", "p1", "ns2", "2026-01-01T00:00:00Z"))
        assert policy.check_access("s1", "s2", AccessType.WRITE) is False

    def test_write_to_own_namespace_allowed(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        assert policy.check_write("s1", "ns1") is True

    def test_write_to_foreign_namespace_denied(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        assert policy.check_write("s1", "ns_other") is False

    def test_read_own_namespace_allowed(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        assert policy.check_read("s1", "ns1") is True

    def test_read_foreign_namespace_denied(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        assert policy.check_read("s1", "ns_other") is False

    def test_unregistered_session_write_denied(self):
        policy = SessionBoundaryPolicy()
        assert policy.check_write("unknown", "ns1") is False

    def test_unregistered_session_read_denied(self):
        policy = SessionBoundaryPolicy()
        assert policy.check_read("unknown", "ns1") is False

    def test_audit_log_captures_cross_session_denial(self):
        policy = SessionBoundaryPolicy()
        policy.register_session(SessionRecord("s1", "p1", "ns1", "2026-01-01T00:00:00Z"))
        policy.register_session(SessionRecord("s2", "p1", "ns2", "2026-01-01T00:00:00Z"))
        policy.check_access("s1", "s2", AccessType.WRITE)
        log = policy.audit_log
        denial = [e for e in log if e.get("action") == "cross_session_denied"]
        assert len(denial) >= 1
