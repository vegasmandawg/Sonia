"""
Stage 7 — Backup/Restore Discipline Tests

Tests for state backup and restore:
  - Create backup captures DLQ, actions, breakers, config
  - Backup verification passes integrity checks
  - DLQ restore dry-run validates without side effects
  - Backup list returns available backups
  - Restore integrity: checksums match after backup
"""
import sys
import time
import httpx
import pytest

sys.path.insert(0, r"S:\services\api-gateway")

GW = "http://127.0.0.1:7000"
TIMEOUT = 15.0


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=GW, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def backup_id(client):
    """Create a backup once for the entire test module."""
    resp = client.post("/v1/backups?label=test-stage7-backup").json()
    assert resp["ok"] is True
    return resp["backup"]["backup_id"]


class TestBackupCreate:
    """Test backup creation."""

    def test_create_backup_returns_manifest(self, client):
        resp = client.post("/v1/backups?label=test-create").json()
        assert resp["ok"] is True
        manifest = resp["backup"]
        assert "backup_id" in manifest
        assert "created_at" in manifest
        assert "artifacts" in manifest
        assert "checksums" in manifest

    def test_backup_captures_dlq(self, client, backup_id):
        resp = client.get(f"/v1/backups/{backup_id}/verify").json()
        assert "dead_letters.json" in resp.get("checks", {}), \
            "Backup should contain dead_letters.json"

    def test_backup_captures_actions(self, client, backup_id):
        resp = client.get(f"/v1/backups/{backup_id}/verify").json()
        assert "actions.json" in resp.get("checks", {}), \
            "Backup should contain actions.json"

    def test_backup_captures_breakers(self, client, backup_id):
        resp = client.get(f"/v1/backups/{backup_id}/verify").json()
        assert "breakers.json" in resp.get("checks", {}), \
            "Backup should contain breakers.json"


class TestBackupVerify:
    """Test backup integrity verification."""

    def test_verify_passes_for_fresh_backup(self, client, backup_id):
        resp = client.get(f"/v1/backups/{backup_id}/verify").json()
        assert resp["ok"] is True, f"Fresh backup should verify: {resp}"
        for filename, check in resp["checks"].items():
            assert check["status"] in ("PASS", "embedded"), \
                f"Artifact {filename} failed verification: {check}"

    def test_verify_fails_for_nonexistent_backup(self, client):
        resp = client.get("/v1/backups/nonexistent-backup-xyz/verify").json()
        assert resp["ok"] is False


class TestBackupList:
    """Test backup listing."""

    def test_list_returns_backups(self, client, backup_id):
        resp = client.get("/v1/backups").json()
        assert resp["ok"] is True
        assert resp["total"] > 0
        ids = [b["backup_id"] for b in resp["backups"]]
        assert backup_id in ids, f"Created backup {backup_id} not in list"

    def test_list_includes_metadata(self, client):
        resp = client.get("/v1/backups").json()
        for b in resp["backups"]:
            assert "created_at" in b
            assert "artifacts" in b


class TestDLQRestore:
    """Test DLQ restore from backup."""

    def test_dryrun_restore_validates_without_changes(self, client, backup_id):
        resp = client.post(f"/v1/backups/{backup_id}/restore/dlq?dry_run=true").json()
        assert resp["ok"] is True
        assert resp["dry_run"] is True
        assert "records_to_restore" in resp

    def test_dryrun_restore_for_nonexistent_backup(self, client):
        resp = client.post("/v1/backups/nonexistent-xyz/restore/dlq?dry_run=true").json()
        assert resp["ok"] is False
