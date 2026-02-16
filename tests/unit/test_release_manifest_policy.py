"""Tests for release_manifest_policy — completeness, metadata, hashes."""
import sys, hashlib
sys.path.insert(0, r"S:\services\api-gateway")

import pytest
from release_manifest_policy import (
    ManifestEntry, ReleaseMetadata, ReleaseManifestChecker,
    REQUIRED_MANIFEST_ENTRIES,
)


def _full_checker():
    mc = ReleaseManifestChecker()
    mc.set_metadata(ReleaseMetadata("4.1.0", "8.0", "2025-01-01T00:00:00Z", "abc", "v4.1.0"))
    for name in REQUIRED_MANIFEST_ENTRIES:
        h = hashlib.sha256(name.encode()).hexdigest()
        mc.add_entry(ManifestEntry(name, h, 100))
    return mc


class TestCompleteness:
    def test_complete_manifest(self):
        mc = _full_checker()
        assert mc.manifest_complete()
        assert mc.all_hashes_present()

    def test_missing_entry_detected(self):
        mc = ReleaseManifestChecker()
        mc.set_metadata(ReleaseMetadata("4.1.0", "8.0", "2025-01-01T00:00:00Z", "abc", "v4.1.0"))
        mc.add_entry(ManifestEntry("gate-report.json", "a" * 64, 100))
        missing = mc.missing_entries()
        assert len(missing) > 0
        assert not mc.manifest_complete()

    def test_missing_hash_detected(self):
        mc = ReleaseManifestChecker()
        mc.set_metadata(ReleaseMetadata("4.1.0", "8.0", "2025-01-01T00:00:00Z", "abc", "v4.1.0"))
        mc.add_entry(ManifestEntry("gate-report.json", "", 100))
        assert "gate-report.json" in mc.entries_without_hash()


class TestMetadata:
    def test_valid_metadata(self):
        mc = _full_checker()
        assert mc.metadata_valid()

    def test_bad_version(self):
        mc = ReleaseManifestChecker()
        mc.set_metadata(ReleaseMetadata("not-semver", "8.0", "2025-01-01T00:00:00Z", "abc", "vnot-semver"))
        assert not mc.metadata_valid()

    def test_tag_version_mismatch(self):
        mc = ReleaseManifestChecker()
        mc.set_metadata(ReleaseMetadata("4.1.0", "8.0", "2025-01-01T00:00:00Z", "abc", "v4.0.0"))
        assert not mc.metadata_valid()

    def test_no_metadata_fails(self):
        mc = ReleaseManifestChecker()
        assert not mc.metadata_valid()


class TestAudit:
    def test_full_audit_pass(self):
        mc = _full_checker()
        audit = mc.full_audit()
        assert audit["overall_pass"]

    def test_manifest_hash_deterministic(self):
        mc = _full_checker()
        h1 = mc.compute_manifest_hash()
        h2 = mc.compute_manifest_hash()
        assert h1 == h2


# --- E3 negative-path tests ---

class TestNegativePaths:
    def test_bad_timestamp_rejects(self):
        m = ReleaseMetadata("4.1.0", "8.0", "not-a-timestamp", "abc", "v4.1.0")
        assert not m.timestamp_valid()

    def test_empty_version_rejects(self):
        m = ReleaseMetadata("", "8.0", "2025-01-01T00:00:00Z", "abc", "v")
        assert not m.version_valid()

    def test_hash_too_short_detected(self):
        mc = ReleaseManifestChecker()
        mc.add_entry(ManifestEntry("gate-report.json", "short", 100))
        assert "gate-report.json" in mc.entries_without_hash()

    def test_audit_fails_with_missing_and_bad_meta(self):
        mc = ReleaseManifestChecker()
        audit = mc.full_audit()
        assert not audit["overall_pass"]
        assert len(audit["missing_entries"]) == len(REQUIRED_MANIFEST_ENTRIES)
        assert audit["metadata_valid"] is False

    def test_manifest_hash_changes_with_new_entry(self):
        mc = _full_checker()
        h1 = mc.compute_manifest_hash()
        mc.add_entry(ManifestEntry("extra.txt", "a" * 64, 50))
        h2 = mc.compute_manifest_hash()
        assert h1 != h2

    def test_partial_manifest_not_complete(self):
        mc = ReleaseManifestChecker()
        mc.add_entry(ManifestEntry("gate-report.json", "a" * 64, 100))
        mc.add_entry(ManifestEntry("changelog.md", "b" * 64, 100))
        assert not mc.manifest_complete()
        missing = mc.missing_entries()
        assert len(missing) == len(REQUIRED_MANIFEST_ENTRIES) - 2

    def test_tag_without_v_prefix_accepted(self):
        m = ReleaseMetadata("4.1.0", "8.0", "2025-01-01T00:00:00Z", "abc", "4.1.0")
        assert m.tag_matches_version()
