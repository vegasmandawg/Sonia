"""
Cleanroom parity: verify rebuild produces identical artifacts.

Provides deterministic artifact fingerprinting and parity comparison
between original and cleanroom rebuild outputs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ArtifactFingerprint:
    """Hash fingerprint for a single build artifact."""
    artifact_path: str
    content_hash: str       # SHA-256 of artifact content
    size_bytes: int

    def matches(self, other: "ArtifactFingerprint") -> bool:
        return (
            self.artifact_path == other.artifact_path
            and self.content_hash == other.content_hash
        )


@dataclass
class ParityResult:
    """Result of comparing original vs cleanroom build."""
    total_artifacts: int
    matched: int
    mismatched: List[str]
    missing_in_cleanroom: List[str]
    extra_in_cleanroom: List[str]
    overall_parity: bool

    def to_dict(self) -> dict:
        return {
            "total_artifacts": self.total_artifacts,
            "matched": self.matched,
            "mismatched": self.mismatched,
            "missing_in_cleanroom": self.missing_in_cleanroom,
            "extra_in_cleanroom": self.extra_in_cleanroom,
            "overall_parity": self.overall_parity,
        }


class CleanroomParityChecker:
    """Compares original build artifacts against cleanroom rebuild."""

    def __init__(self):
        self._original: Dict[str, ArtifactFingerprint] = {}
        self._cleanroom: Dict[str, ArtifactFingerprint] = {}

    def register_original(self, fp: ArtifactFingerprint) -> None:
        self._original[fp.artifact_path] = fp

    def register_cleanroom(self, fp: ArtifactFingerprint) -> None:
        self._cleanroom[fp.artifact_path] = fp

    def check_parity(self) -> ParityResult:
        original_paths = set(self._original.keys())
        cleanroom_paths = set(self._cleanroom.keys())

        missing = sorted(original_paths - cleanroom_paths)
        extra = sorted(cleanroom_paths - original_paths)
        common = sorted(original_paths & cleanroom_paths)

        mismatched = []
        matched = 0
        for path in common:
            if self._original[path].matches(self._cleanroom[path]):
                matched += 1
            else:
                mismatched.append(path)

        overall = (
            len(missing) == 0
            and len(extra) == 0
            and len(mismatched) == 0
        )

        return ParityResult(
            total_artifacts=len(original_paths),
            matched=matched,
            mismatched=mismatched,
            missing_in_cleanroom=missing,
            extra_in_cleanroom=extra,
            overall_parity=overall,
        )


def compute_artifact_hash(content: str) -> str:
    """Compute SHA-256 hash for artifact content."""
    return hashlib.sha256(content.encode()).hexdigest()


def fingerprint_from_content(path: str, content: str) -> ArtifactFingerprint:
    """Create an ArtifactFingerprint from string content."""
    return ArtifactFingerprint(
        artifact_path=path,
        content_hash=compute_artifact_hash(content),
        size_bytes=len(content.encode()),
    )
