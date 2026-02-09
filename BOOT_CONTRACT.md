# Sonia Boot Contract v1.0.0

**Baseline Freeze**: `bootable-1.0.0`  
**Date**: 2026-02-08  
**Root**: S:\

This contract defines exact service paths, ports, and required endpoints.
It serves as the regression baseline and prevents path drift during implementation.

---

## Service Paths & Ports

| Service | Path | Port | Language |
|---------|------|------|----------|
| API Gateway | `S:\services\api-gateway` | 7000 | Python 3.11+ |
| Model Router | `S:\services\model-router` | 7010 | Python 3.11+ |
| Memory Engine | `S:\services\memory-engine` | 7020 | Python 3.11+ |
| Pipecat | `S:\services\pipecat` | 7030 | Python 3.11+ |
| OpenClaw | `S:\services\openclaw` | 7040 | Python 3.11+ |
| EVA-OS | `S:\services\eva-os` | 7050 | Python 3.11+ |

---

## Required Entry Points

Each service **MUST** have:

```
<ServicePath>\main.py
```

With a FastAPI app named `app` at module level.

### Startup Command (Exact)

```bash
python -m uvicorn main:app --app-dir <ServicePath> --host 127.0.0.1 --port <Port>
```

---

## Contract Endpoints

### Universal Endpoints (ALL services)

Every service **MUST** implement these exactly:

#### `GET /healthz`
**Response** (200 OK):
```json
{
  "ok": true,
  "service": "<service-name>",
  "timestamp": "2026-02-08T09:30:00.000Z"
}
```

**Timeout**: Must respond within 2 seconds  
**Failure**: Service is considered DOWN if not 200 within 2s

#### `GET /`
**Response** (200 OK):
```json
{
  "service": "<service-name>",
  "status": "online",
  "version": "1.0.0"
}
```

#### `GET /status`
**Response** (200 OK):
```json
{
  "service": "<service-name>",
  "status": "online",
  "timestamp": "2026-02-08T09:30:00.000Z"
}
```

---

## Service-Specific Contracts

### API Gateway (7000)

**Required Endpoints:**

#### `POST /chat`
Request:
```json
{
  "text": "string"
}
```

Response (200 OK):
```json
{
  "status": "ok",
  "message": "string",
  "service": "api-gateway"
}
```

**Definition of Done**: 
- [ ] Route to Model Router for inference
- [ ] Return structured response
- [ ] Error handling for downstream failures

---

### Model Router (7010)

**Required Endpoints:**

#### `GET /route?task_type=text`
Response (200 OK):
```json
{
  "model": "qwen2:7b",
  "provider": "local",
  "config": {
    "context_length": 32000
  }
}
```

**Definition of Done**:
- [ ] Route to appropriate provider
- [ ] Support: text, vision, embeddings tasks
- [ ] Ollama provider working locally
- [ ] Return deterministic routing

---

### Memory Engine (7020)

**Required Endpoints:**

#### `POST /store`
Request:
```json
{
  "type": "fact",
  "content": "string",
  "metadata": {}
}
```

Response (200 OK):
```json
{
  "status": "stored",
  "id": "mem_001",
  "service": "memory-engine"
}
```

#### `POST /recall`
Request:
```json
{
  "query": "string",
  "limit": 10
}
```

Response (200 OK):
```json
{
  "results": [
    {
      "id": "mem_001",
      "content": "string",
      "score": 0.95
    }
  ],
  "count": 1
}
```

#### `GET /search?q=...&limit=10`
Response (200 OK):
```json
{
  "query": "string",
  "results": [],
  "count": 0
}
```

**Definition of Done**:
- [ ] SQLite-backed persistence
- [ ] Schema migrations runnable
- [ ] Data survives restart
- [ ] CRUD operations working
- [ ] Vector search functional

---

### Pipecat (7030)

**Required Endpoints:**

#### `WebSocket /ws/voice`
- Accept WebSocket connections
- Echo received bytes
- Proper connection lifecycle

#### `WebSocket /ws/events`
- Accept WebSocket connections
- Emit structured event objects
- Connection cleanup on close

Response structure:
```json
{
  "type": "session_started|audio_chunk|transcription|tts_audio|session_ended",
  "timestamp": "2026-02-08T09:30:00.000Z",
  "data": {}
}
```

**Definition of Done**:
- [ ] WebSocket endpoints accept connections
- [ ] Sessions have unique IDs
- [ ] Events are structured and timestamped
- [ ] Connections close cleanly

---

### OpenClaw (7040)

**Required Endpoints:**

#### `GET /tools`
Response (200 OK):
```json
{
  "tools": [
    {
      "name": "filesystem.read_file",
      "tier": "TIER_0_READONLY"
    }
  ],
  "total": 17
}
```

#### `POST /execute`
Request:
```json
{
  "tool_name": "filesystem.read_file",
  "args": {
    "path": "S:\\file.txt"
  }
}
```

Response (200 OK):
```json
{
  "status": "executed",
  "tool_name": "filesystem.read_file",
  "result": {},
  "side_effects": []
}
```

Response (501 Not Implemented):
```json
{
  "status": "not_implemented",
  "tool_name": "shell.run_command",
  "message": "Tool not yet implemented"
}
```

**Definition of Done**:
- [ ] Registry is deterministic
- [ ] 3+ tools implemented (filesystem.read_file, filesystem.write_file, shell commands)
- [ ] Unimplemented tools return 501
- [ ] All responses are auditable

---

### EVA-OS (7050)

**Required Endpoints:**

#### `GET /health/all`
Response (200 OK):
```json
{
  "timestamp": "2026-02-08T09:30:00.000Z",
  "services": {
    "api-gateway": {
      "status": "healthy",
      "latency_ms": 10,
      "last_check": "2026-02-08T09:30:00.000Z"
    }
  }
}
```

**Definition of Done**:
- [ ] Polls all downstream services
- [ ] Reports health status
- [ ] Detects timeouts and failures

---

## Startup Contract

### `start-sonia-stack.ps1` Requirements

```powershell
.\start-sonia-stack.ps1
```

Must:
1. ✓ Call `.\scripts\ops\run-*.ps1` for each service
2. ✓ Wait for each service to respond to /healthz
3. **NEW**: Fail fast if any service doesn't respond within timeout
4. **NEW**: Report which service failed with error logs
5. ✓ Display all 6 service endpoints and health status

### Startup Gate Logic

```
For each service:
  1. Start process
  2. Poll /healthz up to N times (timeout = 30s)
  3. If success: continue to next service
  4. If timeout: FAIL and exit
     - Show service that failed
     - Show last 50 lines of stderr
     - Do NOT start remaining services
```

---

## Shutdown Contract

### `stop-sonia-stack.ps1` Requirements

```powershell
.\stop-sonia-stack.ps1
```

Must:
1. ✓ Read PID files
2. ✓ Attempt graceful shutdown
3. **NEW**: Verify process is actually dead before returning
4. **NEW**: Don't claim success if process still running

### Shutdown Gate Logic

```
For each PID:
  1. Send SIGTERM
  2. Wait up to timeout (default 10s)
  3. If process exits: success
  4. If still running: send SIGKILL
  5. Verify process is gone
  6. Only then: delete PID file and report success
```

---

## Logging Contract

### JSON Logging (Required for all services)

Every log line **MUST** be valid JSON:

```json
{
  "timestamp": "2026-02-08T09:30:00.000Z",
  "level": "INFO",
  "service": "api-gateway",
  "correlation_id": "req_001",
  "message": "Request received",
  "path": "/chat",
  "method": "POST",
  "duration_ms": 45
}
```

### Timestamp Format
ISO 8601 with milliseconds: `2026-02-08T09:30:00.123Z`

### Correlation ID
- Generated per request
- Propagated through inter-service calls
- Enables request tracing across services

### Log Levels
- INFO: Normal operation
- WARN: Degradation or recoverable error
- ERROR: Service-level failure
- DEBUG: Detailed diagnostics (only if LOG_LEVEL=DEBUG)

### Log Output
- All services log to stdout (captured by start script)
- Stderr reserved for startup/fatal errors only
- Format: line-delimited JSON

---

## Dependencies Lock Files

Each service must have:

```
<ServicePath>\requirements.lock
```

Generated from `requirements.txt` with exact versions:

```
# S:\services\api-gateway\requirements.lock
# Generated: 2026-02-08 with pip-compile
fastapi==0.116.1
uvicorn==0.35.0
pydantic==2.11.7
# ... (complete pinned dependencies)
```

Purpose:
- Reproducible builds
- Audit trail of exact versions used
- Prevention of transitive dependency updates

---

## Health Check Contract

### Service Health Status

A service is considered:

**Healthy** (✓):
- Responds to /healthz within 2 seconds
- Returns 200 with `{"ok": true, ...}`
- All downstream dependencies available

**Degraded** (⚠):
- Responds to /healthz within 5 seconds
- Returns 200 but with warnings in response
- Some features limited but service running

**Unhealthy** (✗):
- Doesn't respond within 5 seconds OR
- Returns non-200 status OR
- Process crashed or unresponsive

### Startup Health Check

During `start-sonia-stack.ps1`:
- Poll /healthz every 500ms
- Maximum 30 seconds total wait
- Fail and stop if any service unhealthy

### Runtime Health Check

EVA-OS at `GET /health/all`:
- Poll each service /healthz every 10 seconds
- Report status to caller
- Alert if any service becomes unhealthy

---

## Regression Prevention

### Tests Required

Before any implementation:
```powershell
.\tests\contract\test-health-endpoints.ps1
.\tests\contract\test-required-endpoints.ps1
.\tests\contract\test-startup-gate.ps1
.\tests\contract\test-shutdown-gate.ps1
```

These validate:
- [ ] All endpoints respond
- [ ] All responses match schema
- [ ] Startup succeeds only if all services healthy
- [ ] Shutdown waits for process death

### Path Integrity Check

```powershell
# Verify all service directories exist
Get-ChildItem S:\services\*/main.py | Should -HaveCount 6
```

### Port Integrity Check

```powershell
# Verify no hardcoded ports elsewhere
Select-String -Path S:\services\*/main.py -Pattern "port" | Should -BeNullOrEmpty
```

---

## Breaking Changes Policy

Any change to this contract **MUST**:
1. Update version number (1.0.0 → 1.0.1)
2. Document change in CHANGELOG.md
3. Update all service implementations
4. Pass regression tests
5. Create new snapshot tag

---

## Snapshots

### bootable-1.0.0 (Current)
- Baseline: all services respond to /healthz
- Startup gate: not yet implemented
- Shutdown gate: not yet implemented
- Logging: not JSON standardized
- Persistence: not yet implemented

### Next Snapshots (TBD)
- memory-1.0.0 - Memory Engine persistence complete
- routing-1.0.0 - Model Router working
- executor-1.0.0 - OpenClaw working
- voice-1.0.0 - Pipecat working
- integration-1.0.0 - Full stack working

---

---

## Repair Verification (2026-02-08 repair_20260208-201157)

### Verified Contracts

| Check | Result |
|---|---|
| `/healthz` returns 200 on all 6 services | PASS |
| `/health` returns 404 on all 6 services (no legacy) | PASS |
| Config `health_endpoint` = `/healthz` in sonia-config.json | PASS |
| Port assignments match across config, ports.yaml, services.yaml, launcher | PASS |
| Cold restart cycle (stop, 3s wait, start, health) | PASS |
| Warm restart cycle (stop, 1s wait, start, health) | PASS |
| Error logs clean (0 warnings/errors) after 2 restart cycles | PASS |

### Canonical Scripts (PINNED)

| Purpose | Script | Status |
|---|---|---|
| Start stack | `S:\start-sonia-stack.ps1` | Canonical |
| Stop stack | `S:\stop-sonia-stack.ps1` | Canonical |
| Health gate | `S:\scripts\health-smoke.ps1` | Canonical |
| Per-service | `S:\scripts\ops\run-<name>.ps1` | Canonical |
| Shared lib | `S:\scripts\lib\sonia-stack.ps1` | Canonical |

### Deprecated (DO NOT USE)

| Script | Reason |
|---|---|
| `S:\scripts\ops\run-dev.ps1` | Wrong api-gateway AppDir, duplicates library logic |
| `S:\scripts\ops\start-sonia-stack-v2.ps1` | Superseded by root launcher |
| `S:\scripts\ops\start-all.ps1` | Thin wrapper, use root launcher directly |

### Baseline

- Frozen at: `S:\baselines\sonia_20260208-202218`
- File hashes: see `filehashes.txt` in baseline
- Pip freeze: see `pip-freeze.txt` in baseline (32 packages)

---

**Signed**: bootable-1.0.0 baseline + repair verification
**Date**: 2026-02-08
**Status**: FROZEN — RC1 CANDIDATE
