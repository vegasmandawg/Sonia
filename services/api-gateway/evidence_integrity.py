"""
Evidence Integrity: Hash, timestamp, and source validation.
============================================================
Verifies that evidence artifacts have valid hashes, monotonic timestamps,
and consistent source attribution.

All operations are deterministic and pure.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class EvidenceRecord:
    """A single evidence artifact with integrity metadata."""
    artifact_id: str
    artifact_path: str
    sha256_hash: str
    timestamp_utc: str  # ISO 8601 format
    source: str  # e.g., "gate-v41.py", "pytest", "manual"
    artifact_type: str  # "gate_report", "test_summary", "manifest"

    def verify_hash(self, content_bytes: bytes) -> bool:
        """Check if content matches the recorded hash."""
        computed = hashlib.sha256(content_bytes).hexdigest()
        return computed == self.sha256_hash


class EvidenceHashMissingError(Exception):
    """Raised when a required artifact has no hash."""
    def __init__(self, artifact_id: str):
        self.artifact_id = artifact_id
        super().__init__(f"Missing hash for artifact: {artifact_id}")


class TimestampInconsistencyError(Exception):
    """Raised when timestamps violate monotonicity."""
    def __init__(self, earlier_id: str, later_id: str, earlier_ts: str, later_ts: str):
        self.earlier_id = earlier_id
        self.later_id = later_id
        super().__init__(
            f"Timestamp inconsistency: {earlier_id} ({earlier_ts}) "
            f"should precede {later_id} ({later_ts})"
        )


class EvidenceIntegrityChecker:
    """
    Validates integrity of evidence artifacts.

    Checks:
    - All required artifacts have SHA-256 hashes
    - Timestamps are monotonically consistent within sequences
    - Source attribution is present and valid
    """

    VALID_SOURCES = frozenset([
        "gate-v41.py", "gate-v40.py", "gate-v39.py",
        "pytest", "manual", "ci",
        "provenance-gate", "evidence-gate",
        "dual-pass", "promotion-gate",
    ])

    VALID_ARTIFACT_TYPES = frozenset([
        "gate_report", "test_summary", "manifest",
        "audit_log", "dual_pass_report", "remediation_log",
        "evidence_bundle", "sha256_manifest",
    ])

    def __init__(self):
        self._records: Dict[str, EvidenceRecord] = {}
        self._sequences: Dict[str, List[str]] = {}  # sequence_name -> ordered artifact_ids

    def register(self, record: EvidenceRecord) -> None:
        """Register an evidence record."""
        self._records[record.artifact_id] = record

    def define_sequence(self, name: str, artifact_ids: List[str]) -> None:
        """Define a temporal sequence of artifacts (must be monotonically ordered)."""
        self._sequences[name] = artifact_ids

    def check_hash_presence(self, required_ids: List[str]) -> Dict[str, bool]:
        """
        Check that all required artifact IDs have a hash.
        Returns dict of artifact_id -> has_hash.
        """
        results = {}
        for aid in sorted(required_ids):
            record = self._records.get(aid)
            if record is None:
                results[aid] = False
            elif not record.sha256_hash or len(record.sha256_hash) != 64:
                results[aid] = False
            else:
                results[aid] = True
        return results

    def check_hash_validity(self, artifact_id: str, content_bytes: bytes) -> bool:
        """Verify an artifact's content matches its recorded hash."""
        record = self._records.get(artifact_id)
        if record is None:
            return False
        return record.verify_hash(content_bytes)

    def check_timestamp_monotonicity(self) -> List[Tuple[str, str, str, str]]:
        """
        Check all defined sequences for timestamp monotonicity.
        Returns list of violations: (earlier_id, later_id, earlier_ts, later_ts).
        """
        violations = []
        for seq_name, artifact_ids in sorted(self._sequences.items()):
            prev_ts = None
            prev_id = None
            for aid in artifact_ids:
                record = self._records.get(aid)
                if record is None:
                    continue
                try:
                    current_ts = datetime.fromisoformat(record.timestamp_utc.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if prev_ts is not None and current_ts < prev_ts:
                    violations.append((prev_id, aid, str(prev_ts), str(current_ts)))
                prev_ts = current_ts
                prev_id = aid
        return violations

    def check_source_validity(self) -> Dict[str, bool]:
        """Check that all records have valid sources."""
        results = {}
        for aid in sorted(self._records.keys()):
            record = self._records[aid]
            results[aid] = record.source in self.VALID_SOURCES
        return results

    def check_type_validity(self) -> Dict[str, bool]:
        """Check that all records have valid artifact types."""
        results = {}
        for aid in sorted(self._records.keys()):
            record = self._records[aid]
            results[aid] = record.artifact_type in self.VALID_ARTIFACT_TYPES
        return results

    def full_audit(self, required_ids: Optional[List[str]] = None) -> Dict:
        """
        Run all integrity checks and return a deterministic audit report.
        """
        if required_ids is None:
            required_ids = sorted(self._records.keys())

        hash_presence = self.check_hash_presence(required_ids)
        source_validity = self.check_source_validity()
        type_validity = self.check_type_validity()
        timestamp_violations = self.check_timestamp_monotonicity()

        all_hashes_ok = all(hash_presence.values()) if hash_presence else True
        all_sources_ok = all(source_validity.values()) if source_validity else True
        all_types_ok = all(type_validity.values()) if type_validity else True
        no_ts_violations = len(timestamp_violations) == 0

        return {
            "total_records": len(self._records),
            "hash_presence": hash_presence,
            "all_hashes_present": all_hashes_ok,
            "source_validity": source_validity,
            "all_sources_valid": all_sources_ok,
            "type_validity": type_validity,
            "all_types_valid": all_types_ok,
            "timestamp_violations": timestamp_violations,
            "timestamp_monotonic": no_ts_violations,
            "overall_pass": all_hashes_ok and all_sources_ok and all_types_ok and no_ts_violations,
        }
