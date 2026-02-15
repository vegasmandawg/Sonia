# BACKUP RECOVERY

Backup and recovery procedures for SONIA production system.

## RPO and RTO Targets

### Recovery Point Objective (RPO)
**Target**: 24 hours

**Meaning**: Maximum acceptable data loss is 1 day of memories/state.

**Achieved by**: Daily backups at 2 AM via Windows Task Scheduler.

**Risk**: Data created/modified after last backup (up to 24h) will be lost in disaster recovery.

### Recovery Time Objective (RTO)
**Target**: 60 seconds

**Meaning**: System must be operational within 60 seconds of failure detection.

**Achieved by**: EVA-OS restore drills, automated health checks, fast restart procedures.

**Measured**: Monthly via `release-ops-drill.ps1` (see EVA-OS section).

## Backup Types

### 1. Gateway State Backup

**What's Backed Up**:
- Session store (in-memory sessions serialized to JSON)
- Confirmation queue (pending tool confirmations)
- Circuit breaker state (failure counts, timestamps)
- DLQ entries (dead letter queue)

**Location**: `S:\backups\state\gateway-state-<timestamp>.json`

**Format**: JSON snapshot

**Frequency**: On-demand via API

**Trigger**:
```powershell
# Manual backup
iwr -Method POST http://127.0.0.1:7000/v1/backups -ContentType "application/json" -Body '{}'

# Response
{
  "backup_id": "bkp_abc123",
  "timestamp": "2026-02-15T14:23:45Z",
  "path": "S:\\backups\\state\\gateway-state-20260215-142345.json",
  "manifest": {
    "sessions_count": 5,
    "confirmations_count": 2,
    "dlq_count": 0,
    "breakers_count": 13,
    "sha256": "abc123..."
  }
}
```

**Contents Example**:
```json
{
  "backup_id": "bkp_abc123",
  "timestamp": "2026-02-15T14:23:45Z",
  "sessions": [
    {
      "session_id": "sess_xyz",
      "user_id": "user@example.com",
      "created_at": "2026-02-15T14:00:00Z",
      "last_activity": "2026-02-15T14:20:00Z"
    }
  ],
  "confirmations": [
    {
      "confirmation_id": "conf_001",
      "session_id": "sess_xyz",
      "capability": "file.write",
      "args": {"path": "S:\\test.txt", "content": "hello"},
      "created_at": "2026-02-15T14:22:00Z",
      "ttl": 120
    }
  ],
  "dlq": [],
  "breakers": [...]
}
```

**Limitations**:
- In-memory only (lost on service restart if not backed up)
- No versioning (each backup overwrites previous with new timestamp)
- No encryption (rely on DPAPI for backups directory)

### 2. Database Backup

**What's Backed Up**:
- `S:\data\memory.db` (main SQLite database)
- `S:\data\memory.db-wal` (write-ahead log)
- `S:\data\memory.db-shm` (shared memory file)

**Location**: `S:\backups\db\memory-<timestamp>.db`

**Format**: SQLite database file (binary)

**Frequency**: Daily at 2 AM via Windows Task Scheduler

**Trigger**:
```powershell
# Manual backup (copy file while service running - SQLite supports hot backup)
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item S:\data\memory.db "S:\backups\db\memory-$timestamp.db"
Copy-Item S:\data\memory.db-wal "S:\backups\db\memory-$timestamp.db-wal" -ErrorAction SilentlyContinue
Copy-Item S:\data\memory.db-shm "S:\backups\db\memory-$timestamp.db-shm" -ErrorAction SilentlyContinue

# Automated backup via Task Scheduler
schtasks /create /tn "SONIA DB Backup" /tr "powershell.exe -File S:\scripts\ops\backup-database.ps1" /sc daily /st 02:00
```

**Contents**: Full database (all tables, indexes, schema_version).

**Limitations**:
- No incremental backups (always full backup)
- No backup verification (no automatic restore test)
- No compression (raw SQLite file, ~500MB typical)

## Backup Schedule

### Daily Backups (Automated)
**Time**: 2:00 AM local time

**What**: Database backup only (gateway state not automated)

**Retention**: 7 daily backups (oldest deleted on 8th day)

**Implementation**:
```powershell
# Create Task Scheduler job
schtasks /create /tn "SONIA DB Backup" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File S:\scripts\ops\backup-database.ps1" /sc daily /st 02:00 /ru SYSTEM

# Verify task created
schtasks /query /tn "SONIA DB Backup"
```

**Backup Script** (`S:\scripts\ops\backup-database.ps1`):
```powershell
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupPath = "S:\backups\db\memory-$timestamp.db"
Copy-Item S:\data\memory.db $backupPath -Force
Copy-Item S:\data\memory.db-wal "$backupPath-wal" -Force -ErrorAction SilentlyContinue

# Cleanup old backups (keep last 7)
Get-ChildItem S:\backups\db\memory-*.db | Sort-Object LastWriteTime -Descending | Select-Object -Skip 7 | Remove-Item -Force
```

### On-Demand Backups (Manual)
**When**: Before risky operations (schema migration, bulk delete, restore test)

**What**: Both gateway state and database

**Retention**: Manual cleanup required

**Trigger**:
```powershell
# Backup database
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item S:\data\memory.db "S:\backups\db\memory-manual-$timestamp.db"

# Backup gateway state
iwr -Method POST http://127.0.0.1:7000/v1/backups
```

## Retention Policy

### Daily Backups
**Keep**: Last 7 daily backups (1 week)

**Rationale**: Balance disk space vs. recovery window. 7 days allows recovery from recent corruption or accidental deletion.

**Cleanup**: Automated by backup script (oldest deleted on 8th backup).

### Manual Backups
**Keep**: Indefinitely (until manually deleted)

**Rationale**: Manual backups are for specific events (migrations, tests) and should be retained for audit trail.

**Cleanup**: Manual only. Operators should review S:\backups\db\ quarterly and purge obsolete backups.

### Archived Memories
**Keep**: Soft-deleted memories retained in database for 1 year after archival

**Hard Delete**: Manual SQL (`DELETE FROM memories WHERE archived_at < datetime('now', '-365 days');`)

**Rationale**: Allow recovery from accidental archival within 1 year, then purge to save disk space.

## Encryption

### DPAPI (Data Protection API)
**Status**: Optional (not enabled by default)

**Location**: `S:\backups\` directory

**How to Enable**:
```powershell
# Encrypt backups directory (Windows EFS)
cipher /e /s:S:\backups

# Verify encryption
cipher /c S:\backups\db\memory-latest.db
```

**Protection**: Backups encrypted with user's Windows credential. Only accessible by same user on same machine.

**Limitations**:
- Backups lost if Windows user profile deleted or machine reimaged
- No password-based encryption (tied to Windows login)
- Not portable to other machines without exporting EFS certificate

### Alternative: Manual Encryption
```powershell
# Encrypt backup with password (using 7-Zip)
7z a -p -mhe=on S:\backups\encrypted\memory-backup.7z S:\backups\db\memory-*.db

# Decrypt
7z x S:\backups\encrypted\memory-backup.7z -oS:\temp\
```

## Restore Procedure

### Restore Database

**Scenario**: Database corrupted, need to restore from last known-good backup.

**Steps**:

1. **Stop all services**
   ```powershell
   .\stop-sonia-stack.ps1
   ```

2. **Identify latest backup**
   ```powershell
   $latest = Get-ChildItem S:\backups\db\memory-*.db | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   Write-Host "Latest backup: $($latest.FullName) from $($latest.LastWriteTime)"
   ```

3. **Backup current (corrupt) database**
   ```powershell
   $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
   Move-Item S:\data\memory.db "S:\data\memory-corrupt-$timestamp.db"
   Remove-Item S:\data\memory.db-wal -ErrorAction SilentlyContinue
   Remove-Item S:\data\memory.db-shm -ErrorAction SilentlyContinue
   ```

4. **Restore from backup**
   ```powershell
   Copy-Item $latest.FullName S:\data\memory.db -Force
   ```

5. **Verify database integrity**
   ```powershell
   sqlite3 S:\data\memory.db "PRAGMA integrity_check;"
   # Expected output: "ok"
   ```

6. **Restart services**
   ```powershell
   .\start-sonia-stack.ps1
   ```

7. **Verify health**
   ```powershell
   iwr http://127.0.0.1:7020/healthz
   iwr http://127.0.0.1:7000/healthz
   ```

8. **Test memory search**
   ```powershell
   iwr "http://127.0.0.1:7020/v1/memory/search?query=test&limit=5"
   ```

**Expected Duration**: 2-5 minutes (depends on database size).

### Restore Gateway State

**Scenario**: Service crashed mid-session, need to restore in-progress sessions and confirmations.

**Steps**:

1. **Identify latest gateway backup**
   ```powershell
   $latest = Get-ChildItem S:\backups\state\gateway-state-*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1
   ```

2. **Stop api-gateway**
   ```powershell
   . S:\scripts\lib\sonia-stack.ps1
   Stop-SoniaService -ServiceName "api-gateway" -Port 7000
   ```

3. **Restore via API** (after restarting api-gateway)
   ```powershell
   Start-SoniaService -ServiceName "api-gateway" -ServiceDir "S:\services\api-gateway" -Port 7000
   Wait-SoniaServiceHealth -Port 7000 -MaxWaitSeconds 30

   # Restore DLQ entries only (other state ephemeral)
   iwr -Method POST http://127.0.0.1:7000/v1/backups/restore/dlq -ContentType "application/json" -InFile $latest.FullName
   ```

4. **Verify DLQ restored**
   ```powershell
   iwr http://127.0.0.1:7000/v1/dead-letters | ConvertFrom-Json
   ```

**Expected Duration**: 30 seconds.

**Limitations**:
- Sessions not restored (ephemeral, 30min TTL)
- Confirmations not restored (120s TTL, expired by restore time)
- Only DLQ entries restored (persistent failures)

## Restore Verification Drill

### EVA-OS Automated Drill

**Location**: `services/eva-os/restore_verifier.py`

**Trigger**: Monthly via `release-ops-drill.ps1`

**What It Tests**:
1. Database backup exists and is recent (<24h old)
2. Database restore completes successfully
3. Restored database passes integrity check
4. Memory search returns expected data
5. Services restart after restore within RTO (60s)

**Run Manually**:
```powershell
# Trigger EVA-OS restore drill
iwr -Method POST http://127.0.0.1:7050/v1/drills/restore -ContentType "application/json" -Body '{}'

# Response
{
  "drill_id": "drill_001",
  "status": "completed",
  "rto_actual_seconds": 45,
  "rto_target_seconds": 60,
  "passed": true,
  "steps": [
    {"step": "backup_exists", "passed": true},
    {"step": "restore_database", "passed": true},
    {"step": "integrity_check", "passed": true},
    {"step": "search_test", "passed": true},
    {"step": "service_restart", "passed": true, "duration_seconds": 45}
  ]
}
```

**Drill Cadence**: Monthly (recommended), or before major releases.

**Failure Handling**: If drill fails, export incident bundle and investigate immediately. Do not deploy until drill passes.

## Disaster Recovery Scenarios

### Scenario 1: Database Corruption

**Symptoms**: SQLite errors, integrity check fails, service won't start.

**Recovery**:
1. Restore from latest daily backup (see "Restore Database" procedure)
2. Data loss: Up to 24 hours (RPO)
3. Downtime: 2-5 minutes (RTO target: 60s, actual varies by DB size)

### Scenario 2: Disk Failure (S:\ Drive)

**Symptoms**: I/O errors, files not readable, SMART errors.

**Recovery**:
1. Replace disk or move to new disk
2. Restore from backups (if backups on separate disk)
3. If backups on same disk: **UNRECOVERABLE** (no off-site backups)

**Mitigation**: Store backups on separate disk (e.g., D:\ or network share).

### Scenario 3: Accidental Data Deletion

**Symptoms**: User deleted important memories, wants them back.

**Recovery**:
1. Check if soft-deleted: `SELECT * FROM memories WHERE archived_at IS NOT NULL AND content LIKE '%keyword%';`
2. If soft-deleted: Un-delete: `UPDATE memories SET archived_at = NULL WHERE id = 'abc123';`
3. If hard-deleted: Restore from latest backup (data loss up to RPO)

### Scenario 4: Service Crash with In-Progress Sessions

**Symptoms**: Service crashed, users disconnected, pending confirmations lost.

**Recovery**:
1. Restart service (sessions lost, users must reconnect)
2. Restore DLQ from gateway state backup (pending tool executions)
3. Replay DLQ entries if user requests continuation

**Data Loss**: In-progress sessions (ephemeral), pending confirmations (TTL expired).

### Scenario 5: Complete Machine Failure

**Symptoms**: Hardware failure, OS reinstall, machine lost.

**Recovery**:
1. **If backups on S:\**: UNRECOVERABLE (no off-site backups)
2. **If backups on network share**: Restore backups to new machine, reinstall SONIA, import data

**Mitigation**: Use network share or cloud storage for backups (not implemented by default).

## Backup Hygiene Checklist

### Weekly
- [ ] Verify latest daily backup exists: `Get-ChildItem S:\backups\db\ | Sort-Object LastWriteTime -Descending | Select-Object -First 1`
- [ ] Check backup file size reasonable (not 0 bytes or corrupted)
- [ ] Verify disk space available: `Get-PSDrive S | Select-Object Free`

### Monthly
- [ ] Run EVA-OS restore drill: `iwr -Method POST http://127.0.0.1:7050/v1/drills/restore`
- [ ] Verify RTO <60s: Check drill response `rto_actual_seconds`
- [ ] Test manual restore on non-production copy (clone S:\ to D:\ for testing)
- [ ] Review and purge old manual backups (>90 days old)

### Quarterly
- [ ] Archive old backups to external storage (USB drive, NAS)
- [ ] Test restore from external storage (verify readability)
- [ ] Review retention policy (adjust if needed)
- [ ] Document any changes to backup procedures

## Known Limitations / Non-Goals

1. **No Off-Site Backups**: All backups on same machine (risk: total loss if machine fails).
2. **No Incremental Backups**: Full backups only (disk space inefficient for large DBs).
3. **No Continuous Replication**: No real-time backup or log shipping (RPO limited to backup frequency).
4. **No Automated Restore**: Manual restore procedure required (no one-click recovery).
5. **No Backup Verification**: No automatic restore test (rely on monthly drill for validation).
6. **No Encryption by Default**: Backups stored plaintext (enable DPAPI/EFS manually).
7. **No Versioned Backups**: No rollback to specific point-in-time (only latest N backups).
8. **No Cross-Region Backup**: Single-machine deployment (no geographic redundancy).
9. **No Backup Monitoring**: No alerts if backup fails (manual verification required).
10. **No Backup SLA**: Best-effort backups (no guaranteed backup success).

## Backup Contact

Not applicable (single-user, local-only system). Operators responsible for backup hygiene and recovery.
