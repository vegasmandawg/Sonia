"""
Release lineage: tag -> commit -> changelog linkage and evidence tracing.

Validates that release tags, commits, changelogs, and evidence artifacts
form a consistent, traceable chain.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set


REQUIRED_EVIDENCE_ARTIFACTS: FrozenSet[str] = frozenset([
    "gate-report",
    "test-summary",
    "soak-report",
    "dependency-lock",
    "release-manifest",
])


@dataclass(frozen=True)
class ReleaseTag:
    """A release tag with commit and changelog linkage."""
    tag: str
    commit_sha: str
    version: str
    changelog_entry: Optional[str] = None

    def tag_commit_consistent(self) -> bool:
        """Tag and commit must both be non-empty."""
        return bool(self.tag) and bool(self.commit_sha)

    def has_changelog(self) -> bool:
        return self.changelog_entry is not None and len(self.changelog_entry) > 0

    def tag_matches_version(self) -> bool:
        return self.tag == f"v{self.version}"


@dataclass(frozen=True)
class EvidenceArtifact:
    """A required evidence artifact for release."""
    artifact_type: str    # e.g. "gate-report", "test-summary"
    artifact_path: str
    content_hash: str

    def hash_valid(self) -> bool:
        return bool(self.content_hash) and len(self.content_hash) >= 64


class ReleaseLineageChecker:
    """Validates release lineage consistency."""

    def __init__(self):
        self._tag: Optional[ReleaseTag] = None
        self._evidence: Dict[str, EvidenceArtifact] = {}

    def set_release_tag(self, tag: ReleaseTag) -> None:
        self._tag = tag

    def add_evidence(self, artifact: EvidenceArtifact) -> None:
        self._evidence[artifact.artifact_type] = artifact

    def check_tag_linkage(self) -> bool:
        if self._tag is None:
            return False
        return (
            self._tag.tag_commit_consistent()
            and self._tag.tag_matches_version()
            and self._tag.has_changelog()
        )

    def missing_evidence(self) -> List[str]:
        return sorted(REQUIRED_EVIDENCE_ARTIFACTS - set(self._evidence.keys()))

    def evidence_without_hash(self) -> List[str]:
        return sorted(
            a.artifact_type for a in self._evidence.values()
            if not a.hash_valid()
        )

    def evidence_complete(self) -> bool:
        return (
            len(self.missing_evidence()) == 0
            and len(self.evidence_without_hash()) == 0
        )

    def full_audit(self) -> dict:
        tag_ok = self.check_tag_linkage()
        missing = self.missing_evidence()
        no_hash = self.evidence_without_hash()
        evidence_ok = len(missing) == 0 and len(no_hash) == 0
        return {
            "tag_linkage_valid": tag_ok,
            "evidence_count": len(self._evidence),
            "required_evidence": len(REQUIRED_EVIDENCE_ARTIFACTS),
            "missing_evidence": missing,
            "evidence_without_hash": no_hash,
            "evidence_complete": evidence_ok,
            "overall_pass": tag_ok and evidence_ok,
        }

    def compute_lineage_hash(self) -> str:
        """Deterministic hash of full release lineage."""
        parts = []
        if self._tag:
            parts.append(f"tag:{self._tag.tag}|{self._tag.commit_sha}|{self._tag.version}")
        for a in sorted(self._evidence.values(), key=lambda x: x.artifact_type):
            parts.append(f"evidence:{a.artifact_type}|{a.content_hash}")
        canonical = "\n".join(parts)
        return hashlib.sha256(canonical.encode()).hexdigest()
