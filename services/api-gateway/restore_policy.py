"""
Restore policy: pre/post invariants, hash verification, rollback safety.

Deterministic validation of backup integrity and post-restore state.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RestoreVerdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class BackupRecord:
    """A backup artifact with hash for integrity verification."""
    backup_id: str
    source_service: str
    timestamp: str
    content_hash: str         # SHA-256 of backup content
    content: Optional[str] = None  # actual content for verification

    def verify_hash(self) -> bool:
        if self.content is None:
            return False
        computed = hashlib.sha256(self.content.encode()).hexdigest()
        return computed == self.content_hash


@dataclass
class RestoreCheck:
    name: str
    verdict: RestoreVerdict
    detail: str = ""


class RestorePreconditionError(Exception):
    pass


class RestorePostconditionError(Exception):
    pass


class RestorePreconditionValidator:
    """Validates preconditions before restore is attempted."""

    REQUIRED_PRECONDITIONS = frozenset([
        "backup_exists",
        "backup_hash_valid",
        "target_service_stopped",
        "no_active_transactions",
    ])

    def __init__(self):
        self._checks: Dict[str, bool] = {}

    def set_condition(self, name: str, satisfied: bool) -> None:
        self._checks[name] = satisfied

    def validate(self) -> List[RestoreCheck]:
        results = []
        for precond in sorted(self.REQUIRED_PRECONDITIONS):
            if precond not in self._checks:
                results.append(RestoreCheck(
                    name=precond,
                    verdict=RestoreVerdict.FAIL,
                    detail="precondition not evaluated",
                ))
            elif not self._checks[precond]:
                results.append(RestoreCheck(
                    name=precond,
                    verdict=RestoreVerdict.FAIL,
                    detail="precondition not satisfied",
                ))
            else:
                results.append(RestoreCheck(
                    name=precond,
                    verdict=RestoreVerdict.PASS,
                    detail="ok",
                ))
        return results

    def all_pass(self) -> bool:
        results = self.validate()
        return all(r.verdict == RestoreVerdict.PASS for r in results)

    def missing_preconditions(self) -> List[str]:
        return sorted(
            p for p in self.REQUIRED_PRECONDITIONS
            if p not in self._checks or not self._checks[p]
        )


class RestorePostconditionValidator:
    """Validates state integrity after restore completes."""

    REQUIRED_POSTCONDITIONS = frozenset([
        "state_hash_matches_backup",
        "service_healthy",
        "no_data_corruption",
        "audit_log_written",
    ])

    def __init__(self):
        self._checks: Dict[str, bool] = {}

    def set_condition(self, name: str, satisfied: bool) -> None:
        self._checks[name] = satisfied

    def validate(self) -> List[RestoreCheck]:
        results = []
        for postcond in sorted(self.REQUIRED_POSTCONDITIONS):
            if postcond not in self._checks:
                results.append(RestoreCheck(
                    name=postcond,
                    verdict=RestoreVerdict.FAIL,
                    detail="postcondition not evaluated",
                ))
            elif not self._checks[postcond]:
                results.append(RestoreCheck(
                    name=postcond,
                    verdict=RestoreVerdict.FAIL,
                    detail="postcondition violated",
                ))
            else:
                results.append(RestoreCheck(
                    name=postcond,
                    verdict=RestoreVerdict.PASS,
                    detail="ok",
                ))
        return results

    def all_pass(self) -> bool:
        results = self.validate()
        return all(r.verdict == RestoreVerdict.PASS for r in results)

    def failed_postconditions(self) -> List[str]:
        return sorted(
            p for p in self.REQUIRED_POSTCONDITIONS
            if p not in self._checks or not self._checks[p]
        )


def verify_backup_before_restore(backup: BackupRecord) -> RestoreCheck:
    """Enforce hash verification before any restore attempt."""
    if backup.content is None:
        return RestoreCheck(
            name="backup_hash_verification",
            verdict=RestoreVerdict.FAIL,
            detail="backup content is None, cannot verify hash",
        )
    if backup.verify_hash():
        return RestoreCheck(
            name="backup_hash_verification",
            verdict=RestoreVerdict.PASS,
            detail=f"hash verified: {backup.content_hash[:16]}...",
        )
    return RestoreCheck(
        name="backup_hash_verification",
        verdict=RestoreVerdict.FAIL,
        detail="content hash mismatch",
    )
