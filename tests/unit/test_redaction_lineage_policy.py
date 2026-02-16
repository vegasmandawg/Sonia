"""Tests for redaction_lineage_policy.py — v4.2 E1."""
import sys
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from redaction_lineage_policy import RedactionRecord, RedactionLineageChain


class TestRedactionRecord:
    def test_valid_record(self):
        r = RedactionRecord("r1", "e1", ("field_a",), "pii_removal", "admin",
                            "2026-01-01T00:00:00Z", "")
        assert r.redaction_id == "r1"
        assert r.fingerprint

    def test_empty_redaction_id_rejected(self):
        with pytest.raises(ValueError, match="redaction_id"):
            RedactionRecord("", "e1", ("field_a",), "pii", "admin", "2026-01-01T00:00:00Z", "")

    def test_fingerprint_deterministic(self):
        r1 = RedactionRecord("r1", "e1", ("f1",), "reason", "admin", "2026-01-01T00:00:00Z", "")
        r2 = RedactionRecord("r1", "e1", ("f1",), "reason", "admin", "2026-01-01T00:00:00Z", "")
        assert r1.fingerprint == r2.fingerprint


class TestRedactionLineageChain:
    def _make_chain_of_two(self):
        chain = RedactionLineageChain()
        r1 = RedactionRecord("r1", "e1", ("f1",), "pii", "admin", "2026-01-01T00:00:00Z", "")
        chain.append(r1)
        r2 = RedactionRecord("r2", "e1", ("f2",), "gdpr", "admin",
                              "2026-01-01T01:00:00Z", r1.fingerprint)
        chain.append(r2)
        return chain, r1, r2

    def test_append_first_record(self):
        chain = RedactionLineageChain()
        r = RedactionRecord("r1", "e1", ("f1",), "pii", "admin", "2026-01-01T00:00:00Z", "")
        chain.append(r)
        assert chain.length == 1

    def test_append_chained_record(self):
        chain, r1, r2 = self._make_chain_of_two()
        assert chain.length == 2

    def test_chain_integrity_valid(self):
        chain, _, _ = self._make_chain_of_two()
        result = chain.verify_chain_integrity()
        assert result["valid"] is True
        assert result["length"] == 2

    def test_tamper_detection_broken_chain(self):
        """Negative: inserting a record with wrong previous_hash is rejected."""
        chain = RedactionLineageChain()
        r1 = RedactionRecord("r1", "e1", ("f1",), "pii", "admin", "2026-01-01T00:00:00Z", "")
        chain.append(r1)
        tampered = RedactionRecord("r2", "e1", ("f2",), "gdpr", "admin",
                                    "2026-01-01T01:00:00Z", "wrong_hash")
        with pytest.raises(ValueError, match="Chain integrity violation"):
            chain.append(tampered)

    def test_first_record_must_have_empty_prev(self):
        chain = RedactionLineageChain()
        r = RedactionRecord("r1", "e1", ("f1",), "pii", "admin",
                            "2026-01-01T00:00:00Z", "non_empty")
        with pytest.raises(ValueError, match="empty previous_hash"):
            chain.append(r)

    def test_chain_hash_deterministic(self):
        c1, _, _ = self._make_chain_of_two()
        c2, _, _ = self._make_chain_of_two()
        assert c1.chain_hash() == c2.chain_hash()

    def test_empty_chain_hash(self):
        chain = RedactionLineageChain()
        assert chain.chain_hash()  # non-empty even for empty chain

    def test_get_redactions_for_entry(self):
        chain, _, _ = self._make_chain_of_two()
        reds = chain.get_redactions_for_entry("e1")
        assert len(reds) == 2

    def test_immutability_check(self):
        chain, _, _ = self._make_chain_of_two()
        assert chain.is_immutable_after(0) is True
        assert chain.is_immutable_after(1) is True
