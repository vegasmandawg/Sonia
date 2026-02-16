"""
Release manifest policy: completeness, integrity, and metadata validation.

Ensures release bundles contain all required artifacts with valid
hashes, version strings, and timestamp schemas.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set


REQUIRED_MANIFEST_ENTRIES: FrozenSet[str] = frozenset([
    "gate-report.json",
    "release-manifest.json",
    "requirements-frozen.txt",
    "dependency-lock.json",
    "changelog.md",
])

SEMVER_PATTERN = re.compile(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$')
ISO_TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')


@dataclass(frozen=True)
class ManifestEntry:
    """A single entry in the release manifest."""
    filename: str
    sha256: str
    size_bytes: int = 0

    def hash_present(self) -> bool:
        return bool(self.sha256) and len(self.sha256) >= 64


@dataclass(frozen=True)
class ReleaseMetadata:
    """Release metadata with validation."""
    version: str
    contract_version: str
    timestamp: str
    commit_sha: str
    tag: str

    def version_valid(self) -> bool:
        return bool(SEMVER_PATTERN.match(self.version))

    def timestamp_valid(self) -> bool:
        return bool(ISO_TIMESTAMP_PATTERN.match(self.timestamp))

    def tag_matches_version(self) -> bool:
        return self.tag == f"v{self.version}" or self.tag == self.version


class ReleaseManifestChecker:
    """Validates release manifest completeness and integrity."""

    def __init__(self):
        self._entries: Dict[str, ManifestEntry] = {}
        self._metadata: Optional[ReleaseMetadata] = None

    def set_metadata(self, meta: ReleaseMetadata) -> None:
        self._metadata = meta

    def add_entry(self, entry: ManifestEntry) -> None:
        self._entries[entry.filename] = entry

    def missing_entries(self) -> List[str]:
        return sorted(REQUIRED_MANIFEST_ENTRIES - set(self._entries.keys()))

    def entries_without_hash(self) -> List[str]:
        return sorted(
            e.filename for e in self._entries.values() if not e.hash_present()
        )

    def manifest_complete(self) -> bool:
        return len(self.missing_entries()) == 0

    def all_hashes_present(self) -> bool:
        return len(self.entries_without_hash()) == 0

    def metadata_valid(self) -> bool:
        if self._metadata is None:
            return False
        return (
            self._metadata.version_valid()
            and self._metadata.timestamp_valid()
            and self._metadata.tag_matches_version()
        )

    def full_audit(self) -> dict:
        missing = self.missing_entries()
        no_hash = self.entries_without_hash()
        meta_ok = self.metadata_valid()
        overall = len(missing) == 0 and len(no_hash) == 0 and meta_ok
        return {
            "total_entries": len(self._entries),
            "required_present": len(REQUIRED_MANIFEST_ENTRIES) - len(missing),
            "required_total": len(REQUIRED_MANIFEST_ENTRIES),
            "missing_entries": missing,
            "entries_without_hash": no_hash,
            "metadata_valid": meta_ok,
            "overall_pass": overall,
        }

    def compute_manifest_hash(self) -> str:
        """Compute deterministic hash of manifest content."""
        items = []
        for e in sorted(self._entries.values(), key=lambda x: x.filename):
            items.append(f"{e.filename}|{e.sha256}|{e.size_bytes}")
        canonical = "\n".join(items)
        return hashlib.sha256(canonical.encode()).hexdigest()
