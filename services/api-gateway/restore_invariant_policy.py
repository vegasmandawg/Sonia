"""Restore Invariant Policy — v4.2 E2.

Enforces deterministic pre/post-conditions for restore operations.
Backup hash verification is mandatory before any restore proceeds.
"""
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"


class RestorePhase(Enum):
    PRE_CHECK = "pre_check"
    HASH_VERIFY = "hash_verify"
    RESTORE = "restore"
    POST_VERIFY = "post_verify"
    COMPLETE = "complete"


class PreconditionStatus(Enum):
    MET = "met"
    UNMET = "unmet"
    ERROR = "error"


@dataclass(frozen=True)
class BackupManifest:
    """Manifest describing a backup for restore validation."""
    backup_id: str
    content_hash: str  # SHA-256 of backup content
    entry_count: int
    namespace: str
    timestamp: str

    def __post_init__(self):
        if not self.backup_id:
            raise ValueError("backup_id must be non-empty")
        if not self.content_hash:
            raise ValueError("content_hash must be non-empty")
        if self.entry_count < 0:
            raise ValueError("entry_count must be non-negative")

    @property
    def fingerprint(self) -> str:
        blob = json.dumps({
            "backup_id": self.backup_id,
            "content_hash": self.content_hash,
            "entry_count": self.entry_count,
            "namespace": self.namespace,
            "timestamp": self.timestamp,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class Precondition:
    """A named precondition for restore."""
    name: str
    required: bool
    description: str


@dataclass(frozen=True)
class PostconditionCheck:
    """A postcondition check result."""
    name: str
    passed: bool
    detail: str


class RestoreInvariantPolicy:
    """Enforces deterministic restore invariants."""

    REQUIRED_PRECONDITIONS = (
        Precondition("backup_exists", True, "Backup manifest must be present"),
        Precondition("hash_verified", True, "Backup content hash must match manifest"),
        Precondition("namespace_match", True, "Target namespace must match backup namespace"),
        Precondition("no_active_writes", True, "No active write operations in target namespace"),
    )

    def __init__(self):
        self._restore_log: List[dict] = []

    def check_preconditions(
        self,
        manifest: BackupManifest,
        actual_hash: str,
        target_namespace: str,
        active_writes: bool = False,
    ) -> dict:
        """Evaluate all preconditions for a restore operation.

        Returns dict with 'all_met' (bool) and 'results' (list of status dicts).
        Same inputs always produce the same output — deterministic.
        """
        results = []

        # 1. Backup exists (always true if manifest is provided)
        results.append({
            "name": "backup_exists",
            "status": PreconditionStatus.MET.value,
            "detail": f"backup_id={manifest.backup_id}",
        })

        # 2. Hash verification
        hash_ok = actual_hash == manifest.content_hash
        results.append({
            "name": "hash_verified",
            "status": PreconditionStatus.MET.value if hash_ok else PreconditionStatus.UNMET.value,
            "detail": f"expected={manifest.content_hash[:16]}..., actual={actual_hash[:16]}...",
        })

        # 3. Namespace match
        ns_ok = target_namespace == manifest.namespace
        results.append({
            "name": "namespace_match",
            "status": PreconditionStatus.MET.value if ns_ok else PreconditionStatus.UNMET.value,
            "detail": f"target={target_namespace}, backup={manifest.namespace}",
        })

        # 4. No active writes
        writes_ok = not active_writes
        results.append({
            "name": "no_active_writes",
            "status": PreconditionStatus.MET.value if writes_ok else PreconditionStatus.UNMET.value,
            "detail": f"active_writes={active_writes}",
        })

        all_met = all(r["status"] == PreconditionStatus.MET.value for r in results)

        decision = {
            "all_met": all_met,
            "results": results,
            "restore_allowed": all_met,
        }
        self._restore_log.append({"phase": "precondition", "decision": decision})
        return decision

    def verify_backup_hash(self, manifest: BackupManifest, actual_hash: str) -> dict:
        """Standalone hash verification — mandatory before restore."""
        match = actual_hash == manifest.content_hash
        return {
            "verified": match,
            "backup_id": manifest.backup_id,
            "expected": manifest.content_hash,
            "actual": actual_hash,
        }

    def check_postconditions(
        self,
        manifest: BackupManifest,
        restored_count: int,
        restored_hash: str,
    ) -> dict:
        """Verify post-restore state integrity and parity.

        Deterministic: same inputs always yield the same verdict.
        """
        results = []

        # 1. Entry count parity
        count_ok = restored_count == manifest.entry_count
        results.append(PostconditionCheck(
            "entry_count_parity", count_ok,
            f"expected={manifest.entry_count}, actual={restored_count}"
        ))

        # 2. Content hash parity
        hash_ok = restored_hash == manifest.content_hash
        results.append(PostconditionCheck(
            "content_hash_parity", hash_ok,
            f"expected={manifest.content_hash[:16]}..., actual={restored_hash[:16]}..."
        ))

        # 3. Non-zero restore
        nonzero = restored_count > 0
        results.append(PostconditionCheck(
            "non_zero_restore", nonzero,
            f"restored_count={restored_count}"
        ))

        all_passed = all(r.passed for r in results)
        decision = {
            "all_passed": all_passed,
            "integrity_verified": all_passed,
            "results": [{"name": r.name, "passed": r.passed, "detail": r.detail} for r in results],
        }
        self._restore_log.append({"phase": "postcondition", "decision": decision})
        return decision

    @property
    def restore_log(self) -> List[dict]:
        return list(self._restore_log)
