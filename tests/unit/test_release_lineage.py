"""Tests for release_lineage — tag linkage, evidence tracing."""
import sys, hashlib
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from release_lineage import (
    ReleaseTag, EvidenceArtifact, ReleaseLineageChecker,
    REQUIRED_EVIDENCE_ARTIFACTS,
)


def _full_checker():
    lc = ReleaseLineageChecker()
    lc.set_release_tag(ReleaseTag("v4.1.0", "abc123", "4.1.0", "## v4.1.0 changes"))
    for atype in REQUIRED_EVIDENCE_ARTIFACTS:
        h = hashlib.sha256(atype.encode()).hexdigest()
        lc.add_evidence(EvidenceArtifact(atype, f"reports/{atype}.json", h))
    return lc


class TestTagLinkage:
    def test_valid_linkage(self):
        lc = _full_checker()
        assert lc.check_tag_linkage()

    def test_tag_version_mismatch(self):
        lc = ReleaseLineageChecker()
        lc.set_release_tag(ReleaseTag("v4.0.0", "abc", "4.1.0", "log"))
        assert not lc.check_tag_linkage()

    def test_no_changelog_fails(self):
        lc = ReleaseLineageChecker()
        lc.set_release_tag(ReleaseTag("v4.1.0", "abc", "4.1.0", None))
        assert not lc.check_tag_linkage()

    def test_no_tag_fails(self):
        lc = ReleaseLineageChecker()
        assert not lc.check_tag_linkage()


class TestEvidence:
    def test_complete_evidence(self):
        lc = _full_checker()
        assert lc.evidence_complete()
        assert len(lc.missing_evidence()) == 0

    def test_missing_evidence_detected(self):
        lc = ReleaseLineageChecker()
        lc.set_release_tag(ReleaseTag("v4.1.0", "abc", "4.1.0", "log"))
        assert len(lc.missing_evidence()) == len(REQUIRED_EVIDENCE_ARTIFACTS)

    def test_evidence_without_hash(self):
        lc = ReleaseLineageChecker()
        lc.add_evidence(EvidenceArtifact("gate-report", "path", ""))
        assert "gate-report" in lc.evidence_without_hash()

    def test_full_audit_pass(self):
        lc = _full_checker()
        audit = lc.full_audit()
        assert audit["overall_pass"]

    def test_lineage_hash_deterministic(self):
        lc1 = _full_checker()
        lc2 = _full_checker()
        assert lc1.compute_lineage_hash() == lc2.compute_lineage_hash()


# --- E3 negative-path tests ---

class TestNegativePaths:
    def test_empty_tag_fails_consistency(self):
        t = ReleaseTag("", "abc", "4.1.0")
        assert not t.tag_commit_consistent()

    def test_empty_commit_fails_consistency(self):
        t = ReleaseTag("v4.1.0", "", "4.1.0")
        assert not t.tag_commit_consistent()

    def test_evidence_short_hash_invalid(self):
        e = EvidenceArtifact("gate-report", "path", "tooshort")
        assert not e.hash_valid()

    def test_evidence_empty_hash_invalid(self):
        e = EvidenceArtifact("gate-report", "path", "")
        assert not e.hash_valid()

    def test_audit_fails_tag_only(self):
        lc = ReleaseLineageChecker()
        lc.set_release_tag(ReleaseTag("v4.1.0", "abc", "4.1.0", "log"))
        audit = lc.full_audit()
        assert not audit["overall_pass"]
        assert audit["tag_linkage_valid"] is True
        assert len(audit["missing_evidence"]) > 0

    def test_audit_fails_evidence_only(self):
        lc = ReleaseLineageChecker()
        for atype in REQUIRED_EVIDENCE_ARTIFACTS:
            h = hashlib.sha256(atype.encode()).hexdigest()
            lc.add_evidence(EvidenceArtifact(atype, f"reports/{atype}.json", h))
        audit = lc.full_audit()
        assert not audit["overall_pass"]
        assert audit["tag_linkage_valid"] is False
        assert audit["evidence_complete"] is True

    def test_lineage_hash_changes_with_extra_evidence(self):
        lc = _full_checker()
        h1 = lc.compute_lineage_hash()
        lc.add_evidence(EvidenceArtifact("extra-report", "path", "a" * 64))
        h2 = lc.compute_lineage_hash()
        assert h1 != h2

    def test_tag_mismatch_version_v_prefix(self):
        t = ReleaseTag("v4.2.0", "abc", "4.1.0", "log")
        assert not t.tag_matches_version()
