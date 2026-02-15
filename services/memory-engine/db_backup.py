"""
DatabaseBackupManager: Hot-backup module for SQLite WAL-mode databases.

Provides online backup via sqlite3.backup(), optional DPAPI encryption,
verification, restoration, and retention management.
"""

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import pywin32 for DPAPI encryption
try:
    import win32crypt

    DPAPI_AVAILABLE = True
except ImportError:
    DPAPI_AVAILABLE = False
    logger.warning(
        "pywin32 not available - database encryption will be disabled. "
        "Install pywin32 for DPAPI encryption support."
    )


@dataclass
class BackupManifest:
    """Manifest for a database backup."""

    backup_id: str
    timestamp: str
    db_path: str
    backup_path: str
    sha256: str
    size_bytes: int
    label: Optional[str]
    encrypted: bool
    wal_mode: bool


class DatabaseBackupManager:
    """
    Hot-backup manager for SQLite databases.

    Uses sqlite3.backup() API for online backup without locking the database.
    Supports optional DPAPI encryption on Windows.
    """

    def __init__(
        self,
        db_path: str = r"S:\data\memory.db",
        backup_dir: str = r"S:\backups\db",
        max_backups: int = 7,
        encrypt: bool = True,
    ):
        """
        Initialize backup manager.

        Args:
            db_path: Path to source database
            backup_dir: Directory for backup storage
            max_backups: Maximum backups to retain
            encrypt: Enable DPAPI encryption (requires pywin32)
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.max_backups = max_backups
        self.encrypt = encrypt and DPAPI_AVAILABLE

        if encrypt and not DPAPI_AVAILABLE:
            logger.warning(
                "Encryption requested but pywin32 not available - "
                "backups will not be encrypted"
            )

        # Ensure backup directory exists
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            f"DatabaseBackupManager initialized: db={db_path}, "
            f"backup_dir={backup_dir}, max_backups={max_backups}, "
            f"encrypt={self.encrypt}"
        )

    def _compute_sha256(self, file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    def _encrypt_file(self, file_path: Path) -> Path:
        """
        Encrypt file using Windows DPAPI.

        Returns path to encrypted file (.db.enc).
        """
        if not DPAPI_AVAILABLE:
            raise RuntimeError("DPAPI encryption not available")

        with open(file_path, "rb") as f:
            plaintext = f.read()

        # Encrypt using DPAPI
        encrypted = win32crypt.CryptProtectData(
            plaintext, "SONIA Memory DB Backup", None, None, None, 0
        )

        # Write encrypted file
        encrypted_path = file_path.with_suffix(file_path.suffix + ".enc")
        with open(encrypted_path, "wb") as f:
            f.write(encrypted)

        # Remove unencrypted file
        file_path.unlink()

        logger.info(f"Encrypted backup: {encrypted_path}")
        return encrypted_path

    def _decrypt_file(self, encrypted_path: Path, output_path: Path) -> None:
        """Decrypt file using Windows DPAPI."""
        if not DPAPI_AVAILABLE:
            raise RuntimeError("DPAPI decryption not available")

        with open(encrypted_path, "rb") as f:
            encrypted = f.read()

        # Decrypt using DPAPI
        _, plaintext = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)

        # Write decrypted file
        with open(output_path, "wb") as f:
            f.write(plaintext)

        logger.info(f"Decrypted backup to: {output_path}")

    def _check_wal_mode(self, db_path: Path) -> bool:
        """Check if database is in WAL mode."""
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0].lower()
            conn.close()
            return mode == "wal"
        except Exception as e:
            logger.warning(f"Failed to check WAL mode: {e}")
            return False

    def create_backup(self, label: Optional[str] = None) -> dict:
        """
        Create hot backup of database.

        Args:
            label: Optional label for backup identification

        Returns:
            Manifest dict with backup metadata
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        # Generate backup ID and paths
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        label_suffix = f"-{label}" if label else ""
        backup_id = f"memory-{timestamp}{label_suffix}"
        backup_filename = f"{backup_id}.db"
        backup_path = self.backup_dir / backup_filename

        logger.info(f"Creating backup: {backup_id}")

        # Perform hot backup using sqlite3.backup()
        try:
            source_conn = sqlite3.connect(str(self.db_path))
            dest_conn = sqlite3.connect(str(backup_path))

            # Online backup
            with dest_conn:
                source_conn.backup(dest_conn)

            source_conn.close()
            dest_conn.close()

            logger.info(f"Hot backup completed: {backup_path}")

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            if backup_path.exists():
                backup_path.unlink()
            raise

        # Check WAL mode
        wal_mode = self._check_wal_mode(self.db_path)

        # Encrypt if requested
        encrypted = False
        if self.encrypt:
            try:
                backup_path = self._encrypt_file(backup_path)
                encrypted = True
            except Exception as e:
                logger.error(f"Encryption failed: {e}")
                # Continue without encryption rather than fail
                encrypted = False

        # Compute checksum
        sha256 = self._compute_sha256(backup_path)
        size_bytes = backup_path.stat().st_size

        # Create manifest
        manifest = BackupManifest(
            backup_id=backup_id,
            timestamp=timestamp,
            db_path=str(self.db_path),
            backup_path=str(backup_path),
            sha256=sha256,
            size_bytes=size_bytes,
            label=label,
            encrypted=encrypted,
            wal_mode=wal_mode,
        )

        # Save manifest
        manifest_path = self.backup_dir / f"{backup_id}.manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(asdict(manifest), f, indent=2)

        logger.info(
            f"Backup created: {backup_id} (size={size_bytes}, "
            f"encrypted={encrypted}, wal={wal_mode})"
        )

        return asdict(manifest)

    def verify_backup(self, backup_id: str) -> dict:
        """
        Verify backup integrity.

        Args:
            backup_id: Backup identifier

        Returns:
            Dict with verification results
        """
        manifest_path = self.backup_dir / f"{backup_id}.manifest.json"
        if not manifest_path.exists():
            return {
                "backup_id": backup_id,
                "verified": False,
                "errors": ["Manifest not found"],
            }

        # Load manifest
        with open(manifest_path, "r") as f:
            manifest_data = json.load(f)

        manifest = BackupManifest(**manifest_data)
        backup_path = Path(manifest.backup_path)

        errors = []

        # Check backup file exists
        if not backup_path.exists():
            errors.append("Backup file not found")
            return {
                "backup_id": backup_id,
                "verified": False,
                "errors": errors,
                "manifest": manifest_data,
            }

        # Verify size
        actual_size = backup_path.stat().st_size
        if actual_size != manifest.size_bytes:
            errors.append(
                f"Size mismatch: expected {manifest.size_bytes}, " f"got {actual_size}"
            )

        # Verify checksum
        actual_sha256 = self._compute_sha256(backup_path)
        if actual_sha256 != manifest.sha256:
            errors.append(
                f"SHA-256 mismatch: expected {manifest.sha256}, " f"got {actual_sha256}"
            )

        # If encrypted, try decryption to temp file
        if manifest.encrypted:
            if not DPAPI_AVAILABLE:
                errors.append("Backup is encrypted but DPAPI not available")
            else:
                try:
                    temp_path = self.backup_dir / f"{backup_id}.verify.tmp"
                    self._decrypt_file(backup_path, temp_path)
                    # Verify it's a valid SQLite database
                    try:
                        conn = sqlite3.connect(str(temp_path))
                        cursor = conn.cursor()
                        cursor.execute("SELECT count(*) FROM sqlite_master;")
                        conn.close()
                    except Exception as e:
                        errors.append(f"Decrypted file not valid SQLite: {e}")
                    finally:
                        if temp_path.exists():
                            temp_path.unlink()
                except Exception as e:
                    errors.append(f"Decryption verification failed: {e}")
        else:
            # Verify it's a valid SQLite database
            try:
                conn = sqlite3.connect(str(backup_path))
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM sqlite_master;")
                conn.close()
            except Exception as e:
                errors.append(f"Not a valid SQLite database: {e}")

        verified = len(errors) == 0
        result = {
            "backup_id": backup_id,
            "verified": verified,
            "checks_passed": 4 - len(errors),
            "checks_total": 4,
            "errors": errors,
            "manifest": manifest_data,
        }

        logger.info(f"Backup verification: {backup_id} -> {verified}")
        return result

    def restore_from_backup(
        self,
        backup_id: str,
        target_path: Optional[str] = None,
        dry_run: bool = True,
    ) -> dict:
        """
        Restore database from backup.

        Args:
            backup_id: Backup identifier
            target_path: Target restore path (defaults to original db_path)
            dry_run: If True, verify only without actual restore

        Returns:
            Dict with restoration results
        """
        manifest_path = self.backup_dir / f"{backup_id}.manifest.json"
        if not manifest_path.exists():
            return {
                "backup_id": backup_id,
                "success": False,
                "dry_run": dry_run,
                "error": "Manifest not found",
            }

        # Load manifest
        with open(manifest_path, "r") as f:
            manifest_data = json.load(f)

        manifest = BackupManifest(**manifest_data)
        backup_path = Path(manifest.backup_path)
        target_path = Path(target_path) if target_path else self.db_path

        logger.info(
            f"Restore from backup: {backup_id} -> {target_path} " f"(dry_run={dry_run})"
        )

        # Verify backup first
        verification = self.verify_backup(backup_id)
        if not verification["verified"]:
            return {
                "backup_id": backup_id,
                "success": False,
                "dry_run": dry_run,
                "error": "Backup verification failed",
                "verification": verification,
            }

        if dry_run:
            return {
                "backup_id": backup_id,
                "success": True,
                "dry_run": True,
                "message": "Dry run successful - backup is valid",
                "verification": verification,
                "target_path": str(target_path),
            }

        # Decrypt if necessary
        restore_source = backup_path
        if manifest.encrypted:
            if not DPAPI_AVAILABLE:
                return {
                    "backup_id": backup_id,
                    "success": False,
                    "dry_run": False,
                    "error": "Backup is encrypted but DPAPI not available",
                }

            try:
                temp_path = self.backup_dir / f"{backup_id}.restore.tmp"
                self._decrypt_file(backup_path, temp_path)
                restore_source = temp_path
            except Exception as e:
                return {
                    "backup_id": backup_id,
                    "success": False,
                    "dry_run": False,
                    "error": f"Decryption failed: {e}",
                }

        # Create backup of current database if it exists
        if target_path.exists():
            backup_current = target_path.with_suffix(".db.pre-restore")
            shutil.copy2(target_path, backup_current)
            logger.info(f"Current database backed up to: {backup_current}")

        # Perform restore
        try:
            shutil.copy2(restore_source, target_path)

            # Verify WAL mode on restored database
            wal_mode = self._check_wal_mode(target_path)

            # Clean up temp file if decrypted
            if manifest.encrypted and restore_source.exists():
                restore_source.unlink()

            logger.info(f"Restore completed: {backup_id} -> {target_path}")

            return {
                "backup_id": backup_id,
                "success": True,
                "dry_run": False,
                "target_path": str(target_path),
                "wal_mode": wal_mode,
                "manifest_wal_mode": manifest.wal_mode,
                "wal_mode_match": wal_mode == manifest.wal_mode,
            }

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return {
                "backup_id": backup_id,
                "success": False,
                "dry_run": False,
                "error": str(e),
            }

    def list_backups(self) -> list:
        """
        List all available backups.

        Returns:
            List of manifest dicts, sorted by timestamp (newest first)
        """
        manifests = []

        for manifest_path in self.backup_dir.glob("*.manifest.json"):
            try:
                with open(manifest_path, "r") as f:
                    manifest_data = json.load(f)
                    manifests.append(manifest_data)
            except Exception as e:
                logger.warning(f"Failed to load manifest {manifest_path}: {e}")

        # Sort by timestamp descending
        manifests.sort(key=lambda m: m["timestamp"], reverse=True)

        logger.info(f"Found {len(manifests)} backups")
        return manifests

    def enforce_retention(self) -> dict:
        """
        Enforce retention policy by pruning old backups.

        Returns:
            Dict with retention enforcement results
        """
        manifests = self.list_backups()

        if len(manifests) <= self.max_backups:
            return {
                "pruned": 0,
                "retained": len(manifests),
                "max_backups": self.max_backups,
            }

        # Prune oldest backups
        to_prune = manifests[self.max_backups :]
        pruned_count = 0

        for manifest_data in to_prune:
            backup_id = manifest_data["backup_id"]
            backup_path = Path(manifest_data["backup_path"])
            manifest_path = self.backup_dir / f"{backup_id}.manifest.json"

            try:
                if backup_path.exists():
                    backup_path.unlink()
                if manifest_path.exists():
                    manifest_path.unlink()

                pruned_count += 1
                logger.info(f"Pruned old backup: {backup_id}")

            except Exception as e:
                logger.error(f"Failed to prune backup {backup_id}: {e}")

        logger.info(
            f"Retention enforced: pruned {pruned_count}, "
            f"retained {len(manifests) - pruned_count}"
        )

        return {
            "pruned": pruned_count,
            "retained": len(manifests) - pruned_count,
            "max_backups": self.max_backups,
        }


# Singleton instance
_backup_manager: Optional[DatabaseBackupManager] = None


def get_backup_manager(
    db_path: str = r"S:\data\memory.db",
    backup_dir: str = r"S:\backups\db",
    max_backups: int = 7,
    encrypt: bool = True,
) -> DatabaseBackupManager:
    """
    Get singleton DatabaseBackupManager instance.

    Args:
        db_path: Path to source database
        backup_dir: Directory for backup storage
        max_backups: Maximum backups to retain
        encrypt: Enable DPAPI encryption

    Returns:
        Singleton DatabaseBackupManager instance
    """
    global _backup_manager

    if _backup_manager is None:
        _backup_manager = DatabaseBackupManager(
            db_path=db_path,
            backup_dir=backup_dir,
            max_backups=max_backups,
            encrypt=encrypt,
        )

    return _backup_manager
