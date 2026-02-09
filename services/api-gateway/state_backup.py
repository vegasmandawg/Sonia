"""
Stage 7 — State Backup & Restore

Backup and restore for runtime stateful artifacts:
  - Dead letter queue records
  - Action pipeline records
  - Circuit breaker state
  - Configuration snapshots

Designed for deterministic restore with integrity verification.
"""

import json
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

BACKUP_DIR = Path(r"S:\backups\state")


class StateBackupManager:
    """Manages backup and restore of gateway runtime state."""

    def __init__(self, backup_dir: Path = BACKUP_DIR):
        self._backup_dir = backup_dir
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    async def create_backup(
        self,
        dead_letter_queue,
        action_store,
        breaker_registry,
        label: str = "",
    ) -> Dict[str, Any]:
        """
        Create a full state backup. Returns backup metadata.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_id = f"backup-{ts}"
        backup_path = self._backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)

        manifest = {
            "backup_id": backup_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "artifacts": {},
            "checksums": {},
        }

        # 1. Dead letter queue
        try:
            letters = await dead_letter_queue.list_letters(limit=10000, include_replayed=True)
            dlq_data = [l.to_dict() for l in letters]
            dlq_json = json.dumps(dlq_data, default=str, indent=2)
            (backup_path / "dead_letters.json").write_text(dlq_json, encoding="utf-8")
            manifest["artifacts"]["dead_letters"] = {"count": len(dlq_data)}
            manifest["checksums"]["dead_letters.json"] = hashlib.sha256(dlq_json.encode()).hexdigest()
        except Exception as e:
            manifest["artifacts"]["dead_letters"] = {"error": str(e)}

        # 2. Action pipeline records
        try:
            actions = await action_store.list_actions(limit=10000)
            action_data = [a.dict(exclude_none=True) for a in actions]
            action_json = json.dumps(action_data, default=str, indent=2)
            (backup_path / "actions.json").write_text(action_json, encoding="utf-8")
            manifest["artifacts"]["actions"] = {"count": len(action_data)}
            manifest["checksums"]["actions.json"] = hashlib.sha256(action_json.encode()).hexdigest()
        except Exception as e:
            manifest["artifacts"]["actions"] = {"error": str(e)}

        # 3. Circuit breaker state
        try:
            breaker_data = breaker_registry.summary()
            breaker_metrics = breaker_registry.metrics(last_n=200)
            state_data = {"breakers": breaker_data, "metrics": breaker_metrics}
            state_json = json.dumps(state_data, default=str, indent=2)
            (backup_path / "breakers.json").write_text(state_json, encoding="utf-8")
            manifest["artifacts"]["breakers"] = {"count": len(breaker_data)}
            manifest["checksums"]["breakers.json"] = hashlib.sha256(state_json.encode()).hexdigest()
        except Exception as e:
            manifest["artifacts"]["breakers"] = {"error": str(e)}

        # 4. Configuration snapshot
        try:
            config_files = {}
            for cfg_name in ["sonia-config.json", "requirements-frozen.txt", "dependency-lock.json"]:
                cfg_path = Path(r"S:\config") / cfg_name
                if cfg_path.exists():
                    content = cfg_path.read_text(encoding="utf-8")
                    config_files[cfg_name] = content
                    manifest["checksums"][f"config/{cfg_name}"] = hashlib.sha256(content.encode()).hexdigest()
            config_json = json.dumps(config_files, indent=2)
            (backup_path / "config.json").write_text(config_json, encoding="utf-8")
            manifest["artifacts"]["config"] = {"count": len(config_files)}
        except Exception as e:
            manifest["artifacts"]["config"] = {"error": str(e)}

        # Write manifest
        manifest_json = json.dumps(manifest, indent=2)
        (backup_path / "manifest.json").write_text(manifest_json, encoding="utf-8")

        return manifest

    async def verify_backup(self, backup_id: str) -> Dict[str, Any]:
        """
        Verify backup integrity by re-computing checksums.
        Returns verification result with pass/fail per artifact.
        """
        backup_path = self._backup_dir / backup_id
        manifest_path = backup_path / "manifest.json"

        if not manifest_path.exists():
            return {"ok": False, "error": f"Backup {backup_id} not found"}

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        results = {"ok": True, "backup_id": backup_id, "checks": {}}

        for filename, expected_hash in manifest.get("checksums", {}).items():
            # Handle config/ prefix
            if filename.startswith("config/"):
                # These are stored inside config.json, verify the parent
                results["checks"][filename] = {"status": "embedded", "expected": expected_hash[:16]}
                continue

            file_path = backup_path / filename
            if not file_path.exists():
                results["checks"][filename] = {"status": "MISSING"}
                results["ok"] = False
                continue

            content = file_path.read_text(encoding="utf-8")
            actual_hash = hashlib.sha256(content.encode()).hexdigest()

            if actual_hash == expected_hash:
                results["checks"][filename] = {"status": "PASS", "hash": actual_hash[:16]}
            else:
                results["checks"][filename] = {
                    "status": "FAIL",
                    "expected": expected_hash[:16],
                    "actual": actual_hash[:16],
                }
                results["ok"] = False

        return results

    async def restore_dlq(
        self, backup_id: str, dead_letter_queue, dry_run: bool = True
    ) -> Dict[str, Any]:
        """
        Restore dead letter queue records from backup.
        dry_run=True validates without modifying state.
        """
        backup_path = self._backup_dir / backup_id
        dlq_path = backup_path / "dead_letters.json"

        if not dlq_path.exists():
            return {"ok": False, "error": "dead_letters.json not found in backup"}

        dlq_data = json.loads(dlq_path.read_text(encoding="utf-8"))

        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "records_to_restore": len(dlq_data),
                "backup_id": backup_id,
                "message": "Dry run: no changes made",
            }

        # Real restore: re-enqueue each dead letter
        restored = 0
        errors = 0
        for dl in dlq_data:
            try:
                await dead_letter_queue.enqueue(
                    action_id=dl.get("action_id", "restored"),
                    intent=dl["intent"],
                    params=dl["params"],
                    error_code=dl["error_code"],
                    error_message=dl.get("error_message", ""),
                    correlation_id=dl.get("correlation_id"),
                    session_id=dl.get("session_id"),
                    retries_exhausted=dl.get("retries_exhausted", 0),
                    failure_class=dl.get("failure_class"),
                )
                restored += 1
            except Exception:
                errors += 1

        return {
            "ok": errors == 0,
            "dry_run": False,
            "records_restored": restored,
            "errors": errors,
            "backup_id": backup_id,
        }

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups."""
        backups = []
        for p in sorted(self._backup_dir.iterdir(), reverse=True):
            if p.is_dir() and (p / "manifest.json").exists():
                manifest = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
                backups.append({
                    "backup_id": manifest["backup_id"],
                    "created_at": manifest["created_at"],
                    "label": manifest.get("label", ""),
                    "artifacts": {k: v.get("count", "error") for k, v in manifest.get("artifacts", {}).items()},
                })
        return backups


# Singleton
_backup_mgr = None

def get_backup_manager() -> StateBackupManager:
    global _backup_mgr
    if _backup_mgr is None:
        _backup_mgr = StateBackupManager()
    return _backup_mgr
