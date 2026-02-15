# OPERATIONS RUNBOOK

Day-to-day operations procedures for SONIA production system.

## Start/Stop Procedures

### Start Full Stack
```powershell
# Canonical launcher with pre-flight checks
.\start-sonia-stack.ps1

# With UI launch
.\start-sonia-stack.ps1 -LaunchUI

# Skip health checks (faster, for development)
.\start-sonia-stack.ps1 -SkipHealthCheck

# Development mode with auto-reload
.\start-sonia-stack.ps1 -Reload
```

**Expected Duration**: 15-30 seconds (including health checks)

**Success Criteria**:
- All services report 200 OK on /healthz
- PID files created in S:\state\pids\
- Logs show "Uvicorn running on http://127.0.0.1:PORT"

### Stop Full Stack
```powershell
# Canonical shutdown script
.\stop-sonia-stack.ps1

# Force kill all (if graceful shutdown hangs)
.\stop-sonia-stack.ps1 -Force
```

**Expected Duration**: 3-5 seconds

**Success Criteria**:
- All PID files removed from S:\state\pids\
- Ports 7000-7070 released
- No zombie uvicorn processes

### Restart Single Service

Use this pattern to restart one service without affecting others:

```powershell
# Load library functions
. S:\scripts\lib\sonia-stack.ps1

# Example: Restart API Gateway
Stop-SoniaService -ServiceName "api-gateway" -Port 7000
Start-SoniaService -ServiceName "api-gateway" -ServiceDir "S:\services\api-gateway" -Port 7000
Wait-SoniaServiceHealth -Port 7000 -MaxWaitSeconds 30

# Example: Restart Memory Engine
Stop-SoniaService -ServiceName "memory-engine" -Port 7020
Start-SoniaService -ServiceName "memory-engine" -ServiceDir "S:\services\memory-engine" -Port 7020
Wait-SoniaServiceHealth -Port 7020 -MaxWaitSeconds 30
```

**When to Use**:
- Config changes to single service
- Memory leaks in specific service
- Debugging service-specific issues
- Applying code patches without full restart

### Graceful Restart (Zero Downtime)
Not currently supported. Full stack restart required.

## Health Triage Decision Tree

```
Is /healthz returning 200 OK?
├─ YES → Service healthy, check downstream dependencies
│  ├─ Check /status for additional metrics
│  ├─ Check circuit breaker state (GET /v1/breakers/metrics)
│  └─ Check DLQ depth (GET /v1/dead-letters)
│
└─ NO → Service unhealthy
   ├─ Is port listening?
   │  ├─ NO → Service not started or crashed
   │  │  ├─ Check PID file exists: S:\state\pids\<service>.pid
   │  │  ├─ Check logs: S:\logs\services\<service>.err.log
   │  │  └─ Action: Start service
   │  │
   │  └─ YES → Service hung or failing health check
   │     ├─ Check process alive: Get-Process -Id <pid>
   │     ├─ Check stderr: Get-Content S:\logs\services\<service>.err.log -Tail 50
   │     └─ Action: Restart service
   │
   ├─ Is database accessible (memory-engine only)?
   │  ├─ Check S:\data\memory.db exists and not locked
   │  ├─ Check disk space: Get-PSDrive S
   │  └─ Action: Stop all services, verify DB, restart
   │
   └─ Is Ollama reachable (model-router only)?
      ├─ Check http://127.0.0.1:11434/api/tags
      ├─ Check models loaded: ollama list
      └─ Action: Restart Ollama, verify models
```

## Log Locations and Format

### Service Logs (Stdout/Stderr)
**Location**: `S:\logs\services\`

**Files**:
- `<service>.out.log` - Uvicorn startup, HTTP requests
- `<service>.err.log` - Python tracebacks, exceptions

**Format**: Plain text, timestamped by uvicorn

**Rotation**: Manual (not automated)

**Viewing**:
```powershell
# Tail latest errors
Get-Content S:\logs\services\api-gateway.err.log -Tail 50

# Follow live (like tail -f)
Get-Content S:\logs\services\api-gateway.out.log -Wait -Tail 20

# Search for errors
Select-String -Path S:\logs\services\*.err.log -Pattern "Exception|Error|CRITICAL"
```

### Gateway JSONL Logs (Structured)
**Location**: `S:\logs\gateway\`

**Files**:
- `sessions.jsonl` - Session lifecycle (create, delete, TTL expiry)
- `turns.jsonl` - Turn pipeline (user input, model response, latency)
- `tools.jsonl` - Tool executions (capability, args, result, safety tier)
- `errors.jsonl` - Application errors (exceptions, validation failures)

**Format**: JSON Lines (one JSON object per line)

**Fields** (example from turns.jsonl):
```json
{
  "timestamp": "2026-02-15T14:23:45.123Z",
  "correlation_id": "req_abc123",
  "session_id": "sess_xyz789",
  "turn_id": "turn_001",
  "user_id": "user@example.com",
  "text_input": "What is the weather?",
  "response_text": "I cannot check weather...",
  "latency_ms": {
    "total": 450,
    "memory_read": 12,
    "model": 380,
    "tool": 0,
    "memory_write": 15
  },
  "tool_calls_attempted": 0,
  "tool_calls_executed": 0
}
```

**Viewing**:
```powershell
# Parse JSONL to objects
Get-Content S:\logs\gateway\turns.jsonl | ForEach-Object { $_ | ConvertFrom-Json }

# Filter by correlation_id
Get-Content S:\logs\gateway\*.jsonl | Select-String "req_abc123"

# Extract high-latency turns (>2s)
Get-Content S:\logs\gateway\turns.jsonl | ConvertFrom-Json | Where-Object { $_.latency_ms.total -gt 2000 }
```

### PII Redaction
All logs automatically redact:
- Email addresses → `[EMAIL_REDACTED]`
- SSN → `[SSN_REDACTED]`
- Credit card numbers → `[CC_REDACTED]`
- Phone numbers → `[PHONE_REDACTED]`
- API keys (Bearer tokens, sk-*, api_key=) → `[API_KEY_REDACTED]`

Implementation: `services/shared/log_redaction.py`

## Common Failure Modes and Remediation

### 1. Service Crashed (Exit Code 1)
**Symptoms**: Port not listening, PID file stale, stderr shows traceback

**Diagnosis**:
```powershell
Get-Content S:\logs\services\<service>.err.log -Tail 100
```

**Remediation**:
1. Check for Python import errors (missing dependencies)
2. Check for config syntax errors (invalid JSON)
3. Check for port conflicts (another process using port)
4. Restart service

### 2. High Latency (>2s turn time)
**Symptoms**: Slow responses, timeouts, user complaints

**Diagnosis**:
```powershell
# Check latency breakdown in JSONL
Get-Content S:\logs\gateway\turns.jsonl | ConvertFrom-Json | Select-Object -Last 20 -Property latency_ms

# Check GPU utilization
nvidia-smi dmon -c 10

# Check circuit breaker state
iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json
```

**Remediation**:
1. If model_ms high: Check GPU VRAM, switch to smaller model
2. If memory_read_ms high: Check database size, run VACUUM
3. If tool_ms high: Check tool execution logs, DLQ for retries
4. If total > sum: Check network latency between services

### 3. Memory Search Returns Nothing
**Symptoms**: Empty results from /v1/memory/search despite data written

**Diagnosis**:
```powershell
# Check database not empty
sqlite3 S:\data\memory.db "SELECT COUNT(*) FROM memories WHERE archived_at IS NULL;"

# Check search query
iwr "http://127.0.0.1:7020/v1/memory/search?query=test&limit=10" | ConvertFrom-Json
```

**Remediation**:
1. LIKE search requires literal substring match (no fuzzy search)
2. Check `archived_at IS NULL` (soft-deleted memories excluded)
3. Check `user_id` filter matches (user isolation)
4. Try BM25 search (POST /v1/memory/search with body)

### 4. DLQ Growing
**Symptoms**: Dead letter queue depth increasing, repeated failures

**Diagnosis**:
```powershell
# Check DLQ entries
iwr http://127.0.0.1:7000/v1/dead-letters | ConvertFrom-Json

# Check failure taxonomy
Get-Content S:\logs\gateway\errors.jsonl | ConvertFrom-Json | Group-Object failure_class
```

**Remediation**:
1. Identify failure class (CONNECTION_BOOTSTRAP, TIMEOUT, POLICY_DENIED, etc.)
2. Fix root cause (downstream service, config, safety policy)
3. Replay DLQ entries: `POST /v1/dead-letters/{id}/replay?dry_run=true` (test first)
4. Purge if unrecoverable: `DELETE /v1/dead-letters/{id}`

### 5. Circuit Breaker Stuck OPEN
**Symptoms**: All requests to capability failing, breaker state OPEN

**Diagnosis**:
```powershell
# Check breaker metrics
iwr http://127.0.0.1:7000/v1/breakers/metrics | ConvertFrom-Json

# Check failure window
Get-Content S:\logs\gateway\errors.jsonl | ConvertFrom-Json | Where-Object { $_.capability -eq "file.write" } | Select-Object -Last 10
```

**Remediation**:
1. Wait for HALF_OPEN transition (30s quarantine by default)
2. Fix underlying issue (permissions, disk space, downstream service)
3. Test single request manually to verify recovery
4. Breaker auto-closes after 2 successful recovery probes

### 6. Database Locked
**Symptoms**: "database is locked" errors, memory writes failing

**Diagnosis**:
```powershell
# Check for long-running transactions
sqlite3 S:\data\memory.db "PRAGMA wal_checkpoint(TRUNCATE);"

# Check file locks
handle64 S:\data\memory.db
```

**Remediation**:
1. Stop all services (ensures no writers)
2. Run WAL checkpoint: `sqlite3 S:\data\memory.db "PRAGMA wal_checkpoint(FULL);"`
3. Restart services
4. If persists: backup DB, delete, restore (see BACKUP_RECOVERY.md)

## Incident Bundle Export

When issues occur, export an incident bundle for analysis:

```powershell
# Export last 15 minutes (default)
.\scripts\export-incident-bundle.ps1

# Export last 60 minutes
.\scripts\export-incident-bundle.ps1 -WindowMinutes 60

# Custom output location
.\scripts\export-incident-bundle.ps1 -OutputDir "C:\temp\incident-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

**Bundle Contents**:
- All JSONL logs (sessions, turns, tools, errors) for time window
- Service health snapshots (GET /healthz, GET /status)
- Circuit breaker metrics (GET /v1/breakers/metrics)
- DLQ entries (GET /v1/dead-letters)
- Environment info (Python version, GPU stats, disk space)
- Recent service logs (stderr, last 200 lines)

**Bundle Location**: `S:\incidents\incident-<timestamp>\`

**Use Cases**:
- Debugging production issues
- Auditing tool executions
- Performance analysis
- Sharing with developers

## Quick Reference

### Service Ports
- API Gateway: 7000
- Model Router: 7010
- Memory Engine: 7020
- Pipecat: 7030
- OpenClaw: 7040
- EVA-OS: 7050
- Vision Capture: 7060
- Perception: 7070

### Key Endpoints
- Health: `GET /healthz` (all services)
- Status: `GET /status` (api-gateway only)
- Turn: `POST /v1/turn` (api-gateway)
- Session: `POST /v1/sessions` (api-gateway)
- Stream: `WS /v1/stream/{session_id}` (api-gateway)
- Memory Search: `GET /v1/memory/search?query=X` (memory-engine)
- DLQ: `GET /v1/dead-letters` (api-gateway)
- Breakers: `GET /v1/breakers/metrics` (api-gateway)

### Critical Files
- Config: `S:\config\sonia-config.json`
- Database: `S:\data\memory.db` (WAL mode)
- Logs: `S:\logs\services\`, `S:\logs\gateway\`
- State: `S:\state\pids\`
- Backups: `S:\backups\state\`, `S:\backups\db\`

### Emergency Commands
```powershell
# Force stop all
.\stop-sonia-stack.ps1 -Force

# Kill all Python processes (nuclear option)
Get-Process python | Stop-Process -Force

# Release all ports 7000-7070
7000,7010,7020,7030,7040,7050,7060,7070 | ForEach-Object {
    Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
}

# Backup database before destructive action
Copy-Item S:\data\memory.db S:\backups\db\memory-emergency-$(Get-Date -Format 'yyyyMMdd-HHmmss').db

# Restore from latest backup
$latest = Get-ChildItem S:\backups\db\memory-*.db | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item $latest.FullName S:\data\memory.db -Force
```

## Known Limitations / Non-Goals

1. **No Metrics Dashboard**: Logs are JSONL files, no built-in visualization.
2. **No Alerting**: Manual log monitoring required, no automated alerts.
3. **No Log Rotation**: Operators must manually archive/delete old logs.
4. **No Distributed Tracing**: Correlation IDs only, no OpenTelemetry/Jaeger.
5. **No Hot Config Reload**: Service restart required for config changes.
6. **No Blue/Green Deploys**: Single-instance deployment only.
7. **No A/B Testing**: No traffic splitting or canary deployments.
8. **No Auto-Scaling**: Fixed service count, no horizontal scaling.
9. **No Load Balancing**: Single-instance services, no HA.
10. **No SLA Enforcement**: Best-effort service, no contractual uptime guarantees.
