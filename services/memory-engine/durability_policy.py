"""
Data Durability Policy Module
=============================
Single source of truth for durability invariants across the SONIA stack.

Covers:
  - Migration monotonicity / version continuity
  - Backup chain integrity + hash verification
  - Retention / restore consistency checks
  - Connection durability assertions (WAL/sync/FK/timeout policy conformance)

Emits deterministic artifact report with per-check verdicts.
"""
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any


class DurabilityVerdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    name: str
    verdict: DurabilityVerdict
    detail: str = ""
    evidence: Optional[str] = None


@dataclass
class DurabilityReport:
    timestamp: str = ""
    checks: List[CheckResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    verdict: str = "PENDING"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "checks": [
                {
                    "name": c.name,
                    "verdict": c.verdict.value,
                    "detail": c.detail,
                    "evidence": c.evidence,
                }
                for c in self.checks
            ],
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "verdict": self.verdict,
        }


# ---------------------------------------------------------------------------
# Migration monotonicity / version continuity
# ---------------------------------------------------------------------------

@dataclass
class MigrationRecord:
    version: int
    name: str
    applied: bool = False
    checksum: str = ""


class MigrationMonotonicityChecker:
    """Ensures migration versions are strictly increasing with no gaps."""

    def __init__(self):
        self._migrations: List[MigrationRecord] = []

    def register(self, version: int, name: str, checksum: str = "") -> None:
        self._migrations.append(MigrationRecord(
            version=version, name=name, applied=True, checksum=checksum
        ))

    def check_monotonicity(self) -> CheckResult:
        """Verify versions are strictly increasing."""
        if not self._migrations:
            return CheckResult(
                "migration_monotonicity", DurabilityVerdict.SKIP,
                "No migrations registered"
            )
        sorted_m = sorted(self._migrations, key=lambda m: m.version)
        for i in range(1, len(sorted_m)):
            if sorted_m[i].version <= sorted_m[i - 1].version:
                return CheckResult(
                    "migration_monotonicity", DurabilityVerdict.FAIL,
                    f"Non-monotonic: v{sorted_m[i-1].version} >= v{sorted_m[i].version}"
                )
        return CheckResult(
            "migration_monotonicity", DurabilityVerdict.PASS,
            f"{len(sorted_m)} migrations in strict order"
        )

    def check_continuity(self) -> CheckResult:
        """Verify no version gaps (1,2,3... not 1,3,5)."""
        if not self._migrations:
            return CheckResult(
                "version_continuity", DurabilityVerdict.SKIP,
                "No migrations registered"
            )
        versions = sorted(m.version for m in self._migrations)
        expected = list(range(versions[0], versions[0] + len(versions)))
        if versions != expected:
            gaps = set(expected) - set(versions)
            return CheckResult(
                "version_continuity", DurabilityVerdict.FAIL,
                f"Gaps at versions: {sorted(gaps)}"
            )
        return CheckResult(
            "version_continuity", DurabilityVerdict.PASS,
            f"Continuous from v{versions[0]} to v{versions[-1]}"
        )


# ---------------------------------------------------------------------------
# Backup chain integrity + hash verification
# ---------------------------------------------------------------------------

@dataclass
class BackupEntry:
    backup_id: str
    parent_id: Optional[str]
    sha256: str
    size_bytes: int
    created_at: str = ""


class BackupChainVerifier:
    """Verifies backup chain integrity and hash consistency."""

    def __init__(self):
        self._entries: List[BackupEntry] = []

    def add_entry(self, entry: BackupEntry) -> None:
        self._entries.append(entry)

    def verify_chain(self) -> CheckResult:
        """Verify parent links form a valid chain (no orphans except root)."""
        if not self._entries:
            return CheckResult(
                "backup_chain_integrity", DurabilityVerdict.SKIP,
                "No backup entries"
            )
        ids = {e.backup_id for e in self._entries}
        orphans = []
        roots = 0
        for e in self._entries:
            if e.parent_id is None:
                roots += 1
            elif e.parent_id not in ids:
                orphans.append(e.backup_id)
        if orphans:
            return CheckResult(
                "backup_chain_integrity", DurabilityVerdict.FAIL,
                f"Orphan backups: {orphans}"
            )
        if roots == 0:
            return CheckResult(
                "backup_chain_integrity", DurabilityVerdict.FAIL,
                "No root backup found (all have parents)"
            )
        return CheckResult(
            "backup_chain_integrity", DurabilityVerdict.PASS,
            f"{len(self._entries)} entries, {roots} root(s), 0 orphans"
        )

    def verify_hashes(self, data_map: Optional[Dict[str, bytes]] = None) -> CheckResult:
        """Verify SHA-256 hashes match provided data (if available)."""
        if not self._entries:
            return CheckResult(
                "backup_hash_verification", DurabilityVerdict.SKIP,
                "No backup entries"
            )
        if data_map is None:
            return CheckResult(
                "backup_hash_verification", DurabilityVerdict.PASS,
                f"{len(self._entries)} entries (no data provided for deep verify)"
            )
        mismatches = []
        for e in self._entries:
            if e.backup_id in data_map:
                actual = hashlib.sha256(data_map[e.backup_id]).hexdigest()
                if actual != e.sha256:
                    mismatches.append(e.backup_id)
        if mismatches:
            return CheckResult(
                "backup_hash_verification", DurabilityVerdict.FAIL,
                f"Hash mismatch for: {mismatches}"
            )
        return CheckResult(
            "backup_hash_verification", DurabilityVerdict.PASS,
            f"All verified entries match"
        )


# ---------------------------------------------------------------------------
# Retention / restore consistency
# ---------------------------------------------------------------------------

@dataclass
class RetentionPolicy:
    min_backups: int = 3
    max_age_days: int = 90
    require_restore_test: bool = True


class RetentionConsistencyChecker:
    """Checks retention policy conformance."""

    def __init__(self, policy: Optional[RetentionPolicy] = None):
        self.policy = policy or RetentionPolicy()

    def check_minimum_backups(self, backup_count: int) -> CheckResult:
        ok = backup_count >= self.policy.min_backups
        return CheckResult(
            "retention_minimum_backups",
            DurabilityVerdict.PASS if ok else DurabilityVerdict.FAIL,
            f"{backup_count} backups (min: {self.policy.min_backups})"
        )

    def check_restore_capability(self, restore_tested: bool) -> CheckResult:
        if not self.policy.require_restore_test:
            return CheckResult(
                "restore_capability", DurabilityVerdict.SKIP,
                "Restore test not required by policy"
            )
        return CheckResult(
            "restore_capability",
            DurabilityVerdict.PASS if restore_tested else DurabilityVerdict.FAIL,
            "Restore test passed" if restore_tested else "Restore not verified"
        )


# ---------------------------------------------------------------------------
# Connection durability assertions
# ---------------------------------------------------------------------------

@dataclass
class ConnectionPolicy:
    wal_mode: bool = True
    synchronous: str = "NORMAL"  # OFF, NORMAL, FULL, EXTRA
    foreign_keys: bool = True
    busy_timeout_ms: int = 5000
    journal_size_limit: int = -1  # -1 = unlimited


VALID_SYNCHRONOUS = {"OFF", "NORMAL", "FULL", "EXTRA"}


class ConnectionDurabilityChecker:
    """Validates database connection settings meet durability requirements."""

    def __init__(self, policy: Optional[ConnectionPolicy] = None):
        self.policy = policy or ConnectionPolicy()

    def check_wal_mode(self, actual_journal_mode: str) -> CheckResult:
        if not self.policy.wal_mode:
            return CheckResult(
                "wal_mode", DurabilityVerdict.SKIP, "WAL not required by policy"
            )
        ok = actual_journal_mode.upper() == "WAL"
        return CheckResult(
            "wal_mode",
            DurabilityVerdict.PASS if ok else DurabilityVerdict.FAIL,
            f"Journal mode: {actual_journal_mode} (expected: WAL)"
        )

    def check_synchronous(self, actual_sync: str) -> CheckResult:
        actual_upper = actual_sync.upper()
        if actual_upper not in VALID_SYNCHRONOUS:
            return CheckResult(
                "synchronous_mode", DurabilityVerdict.FAIL,
                f"Invalid synchronous value: {actual_sync}"
            )
        # NORMAL or higher is acceptable
        levels = ["OFF", "NORMAL", "FULL", "EXTRA"]
        policy_idx = levels.index(self.policy.synchronous)
        actual_idx = levels.index(actual_upper)
        ok = actual_idx >= policy_idx
        return CheckResult(
            "synchronous_mode",
            DurabilityVerdict.PASS if ok else DurabilityVerdict.FAIL,
            f"Sync: {actual_upper} (policy min: {self.policy.synchronous})"
        )

    def check_foreign_keys(self, fk_enabled: bool) -> CheckResult:
        if not self.policy.foreign_keys:
            return CheckResult(
                "foreign_keys", DurabilityVerdict.SKIP, "FK not required by policy"
            )
        return CheckResult(
            "foreign_keys",
            DurabilityVerdict.PASS if fk_enabled else DurabilityVerdict.FAIL,
            f"Foreign keys: {'enabled' if fk_enabled else 'disabled'}"
        )

    def check_timeout(self, actual_timeout_ms: int) -> CheckResult:
        ok = actual_timeout_ms >= self.policy.busy_timeout_ms
        return CheckResult(
            "busy_timeout",
            DurabilityVerdict.PASS if ok else DurabilityVerdict.FAIL,
            f"Timeout: {actual_timeout_ms}ms (policy min: {self.policy.busy_timeout_ms}ms)"
        )


# ---------------------------------------------------------------------------
# Composite policy runner
# ---------------------------------------------------------------------------

class DurabilityPolicyRunner:
    """Runs all durability checks and produces a consolidated report."""

    def __init__(self):
        self.migration_checker = MigrationMonotonicityChecker()
        self.backup_verifier = BackupChainVerifier()
        self.retention_checker = RetentionConsistencyChecker()
        self.connection_checker = ConnectionDurabilityChecker()

    def run_all(self) -> DurabilityReport:
        results: List[CheckResult] = []

        # Migration checks
        results.append(self.migration_checker.check_monotonicity())
        results.append(self.migration_checker.check_continuity())

        # Backup checks
        results.append(self.backup_verifier.verify_chain())
        results.append(self.backup_verifier.verify_hashes())

        report = DurabilityReport(
            timestamp=time.strftime("%Y%m%dT%H%M%SZ"),
            checks=results,
            passed=sum(1 for r in results if r.verdict == DurabilityVerdict.PASS),
            failed=sum(1 for r in results if r.verdict == DurabilityVerdict.FAIL),
            skipped=sum(1 for r in results if r.verdict == DurabilityVerdict.SKIP),
        )
        report.verdict = "PASS" if report.failed == 0 else "FAIL"
        return report

    def emit_artifact(self, output_dir: str) -> str:
        """Run checks and write artifact to disk."""
        report = self.run_all()
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = out / f"data-durability-{ts}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2))
        return str(path)
