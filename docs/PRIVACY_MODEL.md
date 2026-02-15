# PRIVACY MODEL

Privacy controls and data handling for SONIA production system.

## Data Inventory

### What's Stored in memory.db

**Location**: `S:\data\memory.db` (SQLite, WAL mode)

**Schema Version**: 9 migrations applied

**Tables**:

1. **memories** - Core memory storage
   - `id` (UUID, primary key)
   - `user_id` (string, user identifier)
   - `session_id` (string, session context)
   - `turn_id` (string, conversation turn)
   - `memory_type` (enum: FACT, PREFERENCE, SYSTEM_STATE, OBSERVATION, TOOL_EVENT, CONFIRMATION)
   - `content` (text, actual memory content)
   - `raw_content` (text, original unprocessed input)
   - `metadata` (JSON, extensible attributes)
   - `created_at` (timestamp, UTC)
   - `archived_at` (timestamp, soft-delete marker, NULL if active)
   - `provenance` (JSON, source tracking)

2. **schema_version** - Migration tracking
   - `version` (int, current schema version)
   - `applied_at` (timestamp, migration timestamp)

**Indexes**:
- `idx_memories_user_id` (for user isolation)
- `idx_memories_session_id` (for session queries)
- `idx_memories_created_at` (for time-range queries)
- `idx_memories_archived_at` (for soft-delete filtering)

**Total Size**: Varies (typically <500MB for 100k memories)

**Backup Frequency**: Daily at 2 AM (via Task Scheduler)

**Retention**: Memories soft-deleted after 90 days (configurable via `auto_archive_days`)

### What's NOT Stored

- **Raw Audio**: Voice input not persisted (unless `save_audio_artifacts: true`)
- **Vision Frames**: Camera frames processed in-memory, not saved
- **Passwords**: No user authentication, no password storage
- **Credit Cards**: Tool policy blocks CC input, never written to DB
- **API Keys**: Environment variables only, never written to memory

## PII Redaction

### Redaction Patterns

**Implementation**: `services/shared/log_redaction.py`

**Patterns Detected**:

1. **Email Addresses**
   - Regex: `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b`
   - Example: `john.doe@example.com` -> `[EMAIL_REDACTED]`

2. **Social Security Numbers**
   - Regex: `\b\d{3}-\d{2}-\d{4}\b`
   - Example: `123-45-6789` -> `[SSN_REDACTED]`

3. **Credit Card Numbers**
   - Regex: `\b(?:\d{4}[-\s]?){3}\d{4}\b`
   - Example: `4111-1111-1111-1111` -> `[CC_REDACTED]`

4. **Phone Numbers**
   - Regex: `\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b`
   - Example: `(555) 123-4567` -> `[PHONE_REDACTED]`

5. **API Keys**
   - Regex: `sk-[a-zA-Z0-9]{20,}|Bearer\s+[a-zA-Z0-9._-]+|api_key=[a-zA-Z0-9]+`
   - Example: `sk-ant-api03-abc123...` -> `[API_KEY_REDACTED]`

### Redaction Behavior

**Automatic Redaction Points**:
- Memory writes (before insert into `memories` table)
- JSONL logs (sessions, turns, tools, errors)
- Service logs (stdout/stderr via logging middleware)
- API responses (tool execution results)
- Incident bundles (exported diagnostics)

**Preserves Semantics**:
- Redaction tokens clearly indicate what was removed
- Does not break JSON structure or log parsing
- Maintains line-by-line JSONL format

**Limitations**:
- Regex-based, may miss obfuscated formats (e.g., base64-encoded PII)
- Cannot redact data already written to database (apply before write)
- Cannot redact encrypted data (must decrypt first, then redact)
- May false-positive on synthetic data (e.g., "test@test.com" redacted)

### Manual Redaction

For data already in database:

```powershell
# Export memories for manual review
sqlite3 S:\data\memory.db "SELECT id, content FROM memories WHERE content LIKE '%@%';" | Out-File S:\temp\emails.txt

# Update single memory
sqlite3 S:\data\memory.db "UPDATE memories SET content = '[REDACTED]' WHERE id = 'abc-123';"

# Bulk redact by pattern (CAUTION: irreversible)
# Not recommended - prefer soft-delete and re-ingest with redaction
```

## Perception Privacy Gate

### Fail-Closed Design

**Implementation**: `services/vision-capture/main.py`, `services/perception/main.py`

**Default State**: Privacy OFF, camera disabled

**Activation**: Explicit user consent required

```json
// Enable vision capture
POST /v1/vision/control
{
  "action": "enable",
  "user_consent": true
}

// Disable vision capture
POST /v1/vision/control
{
  "action": "disable"
}
```

**Fail-Closed Guarantee**:
- Camera never starts without explicit `enable` action
- Power loss or crash resets to disabled state
- No persistent "camera enabled" flag across reboots
- Each session requires fresh consent

**Bypass-Proof**:
- Vision frames rejected if consent flag not set
- Perception service verifies consent before VLM inference
- No backdoor API to skip consent check
- Tests verify fail-closed behavior (see `test_v26_cross_track.py`)

### Consent Model

**Per-Session Consent**: Each session_id requires independent consent

**Consent Persistence**: In-memory only, lost on service restart

**Revocation**: User can disable mid-session via `POST /v1/vision/control {"action": "disable"}`

**Audit Trail**: All consent events logged to `S:\logs\gateway\sessions.jsonl`

```json
{
  "timestamp": "2026-02-15T14:23:45Z",
  "event_type": "vision_consent_granted",
  "session_id": "sess_abc123",
  "user_id": "user@example.com",
  "consent": true
}
```

### Vision Frame Limits

**Max Frame Size**: 1MB per frame (larger frames rejected)

**Max Frame Rate**: 10 fps (rate-limited, frames dropped if exceeded)

**Max Frames Per Turn**: 3 frames (older frames purged from ring buffer)

**Ring Buffer Capacity**: 300 frames max (FIFO eviction)

**Frame Retention**: In-memory only, not persisted to disk (unless `save_audio_artifacts: true` in debug mode)

**Frame Metadata**: Timestamp, resolution, format stored in JSONL logs (not pixel data)

## Data Retention

### Soft-Delete via archived_at

**Mechanism**: `archived_at` column in `memories` table

**Active Memories**: `archived_at IS NULL`

**Archived Memories**: `archived_at IS NOT NULL`

**Auto-Archive**: Memories older than 90 days auto-marked (configurable via `auto_archive_days` in config)

**Archive Job**: Runs daily at 2 AM (same schedule as backups)

```sql
-- Archive old memories
UPDATE memories
SET archived_at = CURRENT_TIMESTAMP
WHERE created_at < datetime('now', '-90 days')
  AND archived_at IS NULL;
```

**Hard Delete**: Manual only (not automated)

```sql
-- Purge archived memories older than 1 year
DELETE FROM memories
WHERE archived_at < datetime('now', '-365 days');

-- Vacuum to reclaim disk space
VACUUM;
```

### Retention Exceptions

**Never Archived** (unless manually marked):
- Memory types: PREFERENCE, PROJECT_STATE, STABLE_CONSTRAINT
- User-flagged important memories (future feature, not implemented)

**Immediate Archive** (on demand):
- User requests deletion via API (future feature)
- Privacy incident response (manual SQL)

## Audit Logging

### Audit Log Locations

**Tool Executions**: `S:\audit\tool-calls.json`

**Perception Events**: `S:\logs\gateway\turns.jsonl` (with `vision_observation` type)

**Consent Events**: `S:\logs\gateway\sessions.jsonl` (with `vision_consent_*` events)

**Memory Writes**: `S:\logs\gateway\turns.jsonl` (with `memory_write_count` field)

### Audit Log Format

**Tool Call Audit** (JSON array):
```json
[
  {
    "timestamp": "2026-02-15T14:23:45Z",
    "correlation_id": "req_abc123",
    "user_id": "user@example.com",
    "capability": "file.read",
    "args": {"path": "S:\\data\\test.txt"},
    "result": {"status": "success", "bytes_read": 1024},
    "safety_tier": "safe_read",
    "confirmation_required": false,
    "execution_time_ms": 12
  }
]
```

**Retention**: 90 days (same as memory retention)

**Access Control**: File system permissions (NTFS ACLs) only, no encryption

### Audit Log Analysis

**Query Examples**:

```powershell
# Count tool calls by capability
Get-Content S:\audit\tool-calls.json | ConvertFrom-Json | Group-Object capability | Select-Object Name, Count

# Find all file.write operations
Get-Content S:\audit\tool-calls.json | ConvertFrom-Json | Where-Object { $_.capability -eq "file.write" }

# Find operations by user
Get-Content S:\audit\tool-calls.json | ConvertFrom-Json | Where-Object { $_.user_id -eq "user@example.com" }

# Find high-tier confirmations
Get-Content S:\audit\tool-calls.json | ConvertFrom-Json | Where-Object { $_.safety_tier -eq "guarded_high" }
```

## Data Breach Response

### Incident Classification

**Severity Levels**:

1. **Critical**: Unauthorized access to S:\data\memory.db (all user data)
2. **High**: Unauthorized access to API keys or secrets
3. **Medium**: Unauthorized tool execution (file.write, shell.run)
4. **Low**: Unauthorized read of logs or non-sensitive files

### Response Procedures

**Critical Breach** (database compromise):
1. Immediately stop all services
2. Disconnect machine from network
3. Export incident bundle
4. Restore database from last known-good backup
5. Audit all memories created since last backup
6. Notify affected users (if multi-user system, future)
7. Rotate all API keys
8. File incident report

**High Breach** (API key compromise):
1. Immediately revoke compromised API key with provider
2. Generate new API key
3. Update environment variable
4. Restart services
5. Audit all model router calls for unauthorized usage
6. Review billing for unexpected charges

**Medium Breach** (unauthorized tool execution):
1. Export incident bundle
2. Review tool audit log for unauthorized calls
3. Identify attack vector (compromised session, injection)
4. Apply fix (patch code, update safety policy)
5. Restart services
6. Monitor for 24h for recurrence

**Low Breach** (unauthorized log access):
1. Review file system audit logs (if enabled)
2. Verify PII redaction applied
3. Document incident
4. No immediate action required (logs designed to be low-sensitivity)

### Data Minimization

**Best Practices**:
- Enable auth (set `auth.enabled: true`) if sharing machine
- Reduce `auto_archive_days` to 30 days for shorter retention
- Disable `save_audio_artifacts` in production
- Run redaction audit monthly
- Purge archived memories quarterly

## Known Limitations / Non-Goals

1. **No Encryption at Rest**: Database stored plaintext (rely on DPAPI for backups, Windows EFS optional).
2. **No Right to Be Forgotten**: Manual SQL required to hard-delete user data (no automated GDPR compliance).
3. **No Data Minimization**: All turn inputs written to memory (no automatic pruning of non-essential data).
4. **No Anonymization**: Soft-delete only, no irreversible anonymization of archived data.
5. **No Access Logs**: No file system audit trail for who read memory.db (enable Windows auditing separately).
6. **No Multi-User Isolation**: Single-user system, `user_id` field not enforced by access control.
7. **No Data Export**: No built-in "download my data" feature (manual SQLite export only).
8. **No Consent Management UI**: Camera consent via API only (no user-facing consent dialog).
9. **No Privacy Impact Assessment**: No formal PIA or DPIA documentation.
10. **No COPPA/GDPR Compliance**: Not designed for regulated environments or minors.

## Privacy Checklist

### Before Deployment
- [ ] Verify PII redaction patterns cover expected data types
- [ ] Disable `save_audio_artifacts` in production config
- [ ] Set `auto_archive_days` to reasonable retention (30-90 days)
- [ ] Confirm camera default state is OFF (fail-closed)
- [ ] Review .gitignore excludes data/, logs/, backups/
- [ ] Test soft-delete and hard-delete procedures

### Monthly Maintenance
- [ ] Audit tool-calls.json for unexpected file access
- [ ] Check memory.db size and archive old data
- [ ] Review JSONL logs for PII leakage (spot check)
- [ ] Verify camera consent events logged correctly
- [ ] Purge archived memories >1 year old (if desired)

### User Requests
- **Request to Delete Data**: Run `UPDATE memories SET archived_at = NOW() WHERE user_id = 'X';` then hard-delete
- **Request to Export Data**: `sqlite3 S:\data\memory.db ".dump" > user_export.sql`
- **Request to Revoke Consent**: `POST /v1/vision/control {"action": "disable"}`

## Privacy Contact

Not applicable (single-user, local-only system). Escalate to codebase maintainer for privacy questions.
