"""Tests for identity_policy.py — v4.2 E1."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from identity_policy import PersonaIdentity, PersonaSiloPolicy


class TestPersonaIdentity:
    def test_valid_persona(self):
        p = PersonaIdentity("p1", "ns1", "Alice", frozenset({"read"}))
        assert p.persona_id == "p1"
        assert p.namespace == "ns1"
        assert p.fingerprint  # non-empty

    def test_empty_persona_id_rejected(self):
        with pytest.raises(ValueError, match="persona_id"):
            PersonaIdentity("", "ns1", "Alice")

    def test_empty_namespace_rejected(self):
        with pytest.raises(ValueError, match="namespace"):
            PersonaIdentity("p1", "", "Alice")

    def test_fingerprint_deterministic(self):
        p1 = PersonaIdentity("p1", "ns1", "Alice")
        p2 = PersonaIdentity("p1", "ns1", "Alice")
        assert p1.fingerprint == p2.fingerprint

    def test_different_personas_different_fingerprints(self):
        p1 = PersonaIdentity("p1", "ns1", "Alice")
        p2 = PersonaIdentity("p2", "ns2", "Bob")
        assert p1.fingerprint != p2.fingerprint


class TestPersonaSiloPolicy:
    def test_register_and_access_same_persona(self):
        policy = PersonaSiloPolicy()
        p = PersonaIdentity("p1", "ns1", "Alice")
        policy.register_persona(p)
        assert policy.check_access("p1", "p1") is True

    def test_cross_persona_access_denied_without_grant(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p1", "ns1", "Alice"))
        policy.register_persona(PersonaIdentity("p2", "ns2", "Bob"))
        assert policy.check_access("p1", "p2") is False

    def test_cross_persona_access_allowed_with_grant(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p1", "ns1", "Alice"))
        policy.register_persona(PersonaIdentity("p2", "ns2", "Bob"))
        policy.grant_cross_access("p2", "p1")  # p1 can access p2
        assert policy.check_access("p1", "p2") is True

    def test_revoke_cross_access(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p1", "ns1", "Alice"))
        policy.register_persona(PersonaIdentity("p2", "ns2", "Bob"))
        policy.grant_cross_access("p2", "p1")
        assert policy.check_access("p1", "p2") is True
        policy.revoke_cross_access("p2", "p1")
        assert policy.check_access("p1", "p2") is False

    def test_unregistered_requester_denied(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p2", "ns2", "Bob"))
        assert policy.check_access("unknown", "p2") is False

    def test_unregistered_target_denied(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p1", "ns1", "Alice"))
        assert policy.check_access("p1", "unknown") is False

    def test_duplicate_registration_idempotent(self):
        policy = PersonaSiloPolicy()
        p = PersonaIdentity("p1", "ns1", "Alice")
        policy.register_persona(p)
        policy.register_persona(p)  # idempotent
        assert policy.registered_count == 1

    def test_reregister_different_namespace_rejected(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p1", "ns1", "Alice"))
        with pytest.raises(ValueError, match="already registered"):
            policy.register_persona(PersonaIdentity("p1", "ns_different", "Alice"))

    def test_audit_log_captures_denials(self):
        policy = PersonaSiloPolicy()
        policy.register_persona(PersonaIdentity("p1", "ns1", "Alice"))
        policy.register_persona(PersonaIdentity("p2", "ns2", "Bob"))
        policy.check_access("p1", "p2")
        log = policy.audit_log
        denial = [e for e in log if e.get("action") == "access_denied"]
        assert len(denial) >= 1
        assert denial[0]["reason"] == "no_cross_persona_grant"
