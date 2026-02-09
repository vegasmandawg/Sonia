# Phase 3 - Production Hardening & Release Control

**Status**: IN PROGRESS  
**Start Date**: 2026-02-08  
**Target Completion**: 2026-02-15  

---

## Phase 3 Overview

Phase 3 shifts from **feature completeness** to **reliability under stress**. This phase proves the system is production-grade through **5 hard blocking gates**:

1. **Gate 1: Go/No-Go** (Day 1) - Startup/shutdown reliability (10 cycles)
2. **Gate 2: Reliability Soak** (48 hours) - Synthetic traffic stress test
3. **Gate 3: Security & Safety** (2-3 days) - Auth, policy enforcement, adversarial tests
4. **Gate 4: Data Durability** (1-2 days) - Backup/restore validation
5. **Gate 5: Integration Tests** (1 day) - 100% pass, deterministic

**Post-Gate Activity** (non-gate): Release ceremony - Tag release-candidate-1 with signed evidence

**Success Criteria**: All 5 gates PASS with zero tolerance; signed evidence bundle created

---

## GATE 1: Go/No-Go (Today)

### Objective
Prove the system can start, run, and stop cleanly 10 consecutive times.

### Execution

**Run**:
```powershell
cd S:\scripts\testing
.\phase3-go-no-go.ps1 -CycleCount 10 -HealthCheckDurationMinutes 30
```

**What it does**:
1. **10 consecutive start/stop cycles** with zombie PID checks
2. **30-minute health check loop** (every 5 seconds)
3. **Integration tests 2x** (determinism verification)
4. **Release artifact bundle** (logs, PIDs, hashes, test results)

### Pass Criteria (Precise Thresholds)
- ✅ **10/10 cycles successful** (100% pass rate, 0 failures)
- ✅ **0 zombie PIDs** after each stop (verified via tasklist)
- ✅ **2,160/2,160 health checks passed** (360 intervals × 6 services = 2,160 individual checks)
  - 30 minutes = 1,800 seconds ÷ 5 seconds per interval = 360 intervals
  - Each interval checks 6 services (ports 7000, 7010, 7020, 7030, 7040, 7050)
  - Total: 360 × 6 = 2,160 expected checks
  - Failure threshold: ANY check returns non-200 → gate fails
- ✅ **2 deterministic integration test runs** (identical pass count and test results)
  - Run 1 result == Run 2 result (exact match required)
  - All 40+ tests pass in both runs
- ✅ **Artifact bundle captured and verified** (logs, PIDs, config hash)

### Failure Handling
- Any cycle failure → **STOP**, investigate root cause
- Any health check miss → **STOP**, check logs
- Non-deterministic tests → **STOP**, identify flaky test
- Missing artifacts → **STOP**, verify permissions

---

## GATE 2: Reliability Soak (48 hours)

### Objective
Prove the system handles continuous synthetic load without degradation.

### Execution

**Traffic profile**:
```
- /v1/chat: 1 req/sec (steady baseline)
- /v1/action: OpenClaw tool executions (shell.run, file.read, file.write, browser.open)
- /session/start + message loop: Voice churn (5 sessions/min create/destroy)
```

**Correlation ID tracking**: All requests carry X-Correlation-ID header for end-to-end tracing

### Metrics to Track

```
Every minute, collect:
- p50, p95, p99 latency for each endpoint
- Error rate (5xx, 4xx, timeout)
- Service restart count
- Memory usage per service
- Active session count (Pipecat)
- Database query latency (Memory Engine)
```

### Pass Criteria
- ✅ Error rate < 0.5%
- ✅ No unbounded memory growth (memory stabilizes after warm-up)
- ✅ No deadlocks (all requests eventually complete)
- ✅ No stuck sessions (all voice sessions close cleanly)
- ✅ No service restarts
- ✅ p95 latency stable (not trending up)

### Monitoring During Soak
- Real-time log streaming to detect anomalies
- Dashboard showing key metrics
- Alert on memory growth > 50MB/hour
- Alert on error rate > 1%
- Alert on restart or deadlock detection

---

## GATE 2B: Integration Test Determinism Lock

**Critical Lock** (applies to Gate 1, Gate 3, and final validation):

Integration tests **MUST** produce identical results on every run.

```
Determinism Lock Definition:
  Run 1: N tests passed, M tests failed
  Run 2: MUST have N tests passed, M tests failed (exact match)
  Run 3 (if retry): MUST have N tests passed, M tests failed (exact match)
  
  Any deviation = NON-DETERMINISTIC = GATE FAILS
  
  Evidence: test-results-run1.json, test-results-run2.json
  Both files must have identical "passed_count" and "failed_count"
```

**Why this matters**:
- Flaky tests hide bugs that surface in production
- If tests pass sometimes and fail sometimes, reliability is unproven
- Determinism = trustworthy results = confident deployment

**Implementation**:
```python
# In test runner: save exact pass/fail counts
test_result_1 = {
    "run": 1,
    "timestamp": "2026-02-14T09:00:00Z",
    "total_tests": 42,
    "passed": 42,
    "failed": 0,
    "test_names": ["test_chat", "test_action", ...]  # exact list
}

test_result_2 = {
    "run": 2,
    "timestamp": "2026-02-14T10:00:00Z",
    "total_tests": 42,
    "passed": 42,
    "failed": 0,
    "test_names": ["test_chat", "test_action", ...]  # must match exactly
}

# Pass only if:
# test_result_1.passed == test_result_2.passed AND
# test_result_1.failed == test_result_2.failed AND
# test_result_1.test_names == test_result_2.test_names
```

**Failure mode**:
- If Run 1 passes 42/42 but Run 2 passes 40/42 → NON-DETERMINISTIC → GATE FAILS
- If Run 2 times out on different test → NON-DETERMINISTIC → GATE FAILS
- If any test order changes → NON-DETERMINISTIC → GATE FAILS

---

## GATE 3: Security & Safety (2-3 days)

### Objective
Prove the system enforces security policies without relying on client-side validation.

### Execution

#### 3.1 Policy Enforcement (Server-Side Only)
**Test**: Send requests that would succeed with weak client-side checks but fail server-side

```powershell
# Test 1: Execute tool without approval (should fail)
curl -X POST http://localhost:7040/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"shell.run","args":{"command":"rm /important/file"}}'
# Expected: Policy denial (TIER_3_DESTRUCTIVE requires EVA-OS approval)

# Test 2: Bypass policy by spoofing approval
curl -X POST http://localhost:7040/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"shell.run","args":{"command":"..."},"approval_token":"fake"}'
# Expected: Invalid token rejection

# Test 3: Execute with valid approval flow
# 1. Call EVA-OS /gate-tool-call
# 2. Get approval token (scope-bound to tool+args)
# 3. Use token in OpenClaw call
# Expected: Success if token valid, failure otherwise
```

**Pass Criteria**: All requests evaluated server-side; no client trust

#### 3.2 Internal Service Auth
**Choose one** (we'll implement token-based):

**Option A: Bearer Token (Simpler)**
- All inter-service calls include X-Service-Token header
- Token issued by EVA-OS on startup
- Token validated on every request
- Token rotation every 24 hours

**Option B: mTLS (Harder, more secure)**
- Each service gets a certificate
- Mutual TLS handshake on every inter-service call
- Certificate renewal via operator script

**Implement**: Option A (Bearer tokens)

```python
# In api-gateway/main.py
async def forward_to_memory(query):
    token = os.getenv("INTERNAL_SERVICE_TOKEN")
    headers = {"X-Service-Token": token}
    response = await memory_client.search(query, headers=headers)
    return response

# In memory-engine/main.py
@app.post("/search")
async def search(request: SearchRequest, x_service_token: str = Header(None)):
    if not validate_token(x_service_token):
        raise HTTPException(status_code=401, detail="Invalid service token")
    # Process request
```

#### 3.3 Command Allowlist Validation
**Test**: Attempt to bypass command restrictions

```powershell
# Test 1: Whitelist bypass (shell.run)
curl -X POST http://localhost:7040/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"shell.run","args":{"command":"cd /tmp && malware.exe"}}'
# Expected: Directory change rejected (not in allowlist)

# Test 2: Path traversal (file.read)
curl -X POST http://localhost:7040/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"file.read","args":{"path":"../../../../etc/passwd"}}'
# Expected: Path traversal blocked (normalized path outside sandbox)

# Test 3: Symlink attack (file.read)
curl -X POST http://localhost:7040/execute \
  -H "Content-Type: application/json" \
  -d '{"tool_name":"file.read","args":{"path":"S:/data/link-to-secret"}}'
# Expected: Symlink detection blocks access
```

**Pass Criteria**: All adversarial commands rejected with clear error codes

#### 3.4 Secrets & Config Validation
**Preflight checks**:
```python
# Before startup:
1. Scan config files for hardcoded secrets (API keys, passwords)
2. Validate all required environment variables are set
3. Check service certificates are valid (if using mTLS)
4. Verify file permissions are restrictive (no world-readable secrets)
5. Validate all policy files syntax
```

**Test**:
```powershell
# Inject secret into config
$config = Get-Content S:\config\sonia-config.json -Raw | ConvertFrom-Json
$config.secrets.api_key = "sk-test-secret"
$config | ConvertTo-Json | Set-Content S:\config\sonia-config.json

# Run preflight checks
.\scripts\ops\preflight-checks.ps1
# Expected: FAIL - Hardcoded secret detected
```

### Pass Criteria
- ✅ All 10+ adversarial tests rejected
- ✅ No secrets in version control or logs
- ✅ Server-side policy enforcement working
- ✅ Inter-service auth tokens validated
- ✅ Preflight checks passing
- ✅ Signed security test report

---

## GATE 4: Data Durability (1-2 days)

### Objective
Prove backup/restore and crash recovery work correctly.

### Execution

#### 4.1 Backup Procedures
```powershell
# Automated backup script
S:\scripts\ops\backup-sonia-state.ps1 -BackupDir "S:\backups\phase3-validation"

# What gets backed up:
# - SQLite database (S:\data\memory\*.db)
# - Session state (S:\data\sessions\*.json)
# - Configuration (S:\config\sonia-config.json)
# - Policy files (S:\config\policies\*.json)
```

#### 4.2 Restore Drill
```powershell
# 1. Stop services
.\stop-sonia-stack.ps1

# 2. Clone fresh S:\ to S:\test-restore\
Copy-Item S:\ -Destination S:\test-restore\ -Recurse

# 3. Corrupt data in fresh copy
Remove-Item S:\test-restore\data\memory\* -Force

# 4. Restore from backup
S:\scripts\ops\restore-sonia-state.ps1 `
  -BackupDir "S:\backups\phase3-validation" `
  -TargetDir "S:\test-restore"

# 5. Start fresh copy
cd S:\test-restore\
.\start-sonia-stack.ps1

# 6. Verify data is intact
curl http://localhost:7020/search -d '{"query":"test"}'
# Expected: Returns pre-backup memories
```

#### 4.3 WAL Consistency Check
```python
# After restore, verify SQLite integrity
import sqlite3
conn = sqlite3.connect("S:\data\memory\sonia.db")
cursor = conn.cursor()
try:
    cursor.execute("PRAGMA integrity_check")
    result = cursor.fetchone()
    assert result[0] == "ok", f"Database integrity check failed: {result}"
except Exception as e:
    raise AssertionError(f"WAL corruption detected: {e}")
```

#### 4.4 RPO/RTO Documentation
```
RPO (Recovery Point Objective):
  - Backup frequency: Every 6 hours
  - Maximum data loss: 6 hours of chat/memory operations
  - Sessions: Lost (recreated on login)
  - Configuration: Point-in-time

RTO (Recovery Time Objective):
  - Restore time from backup: < 5 minutes
  - Services startup: < 2 minutes
  - Health check confirmation: < 1 minute
  - Total: < 8 minutes from failure to operational

Failure Scenarios Covered:
  1. Single service crash (container restart)
  2. Disk full (backup to secondary disk)
  3. Data corruption (restore from backup)
  4. Operator mistake (version control restore)
```

### Pass Criteria
- ✅ Backup script executes without error
- ✅ Restore to clean copy works end-to-end
- ✅ Data integrity verified post-restore
- ✅ WAL consistency checks pass
- ✅ Services start successfully post-restore
- ✅ RPO/RTO documented and acceptable

---

## GATE 5: Observability Baseline (1 day)

### Objective
Prove we can observe system health and diagnose issues.

### Execution

#### 5.1 Standard JSON Logging
**Format** (every service):
```json
{
  "timestamp": "2026-02-08T09:30:45.123Z",
  "level": "INFO",
  "service": "api-gateway",
  "correlation_id": "req_abc123...",
  "operation": "POST /v1/chat",
  "duration_ms": 245.3,
  "status_code": 200,
  "request": {"text": "hello"},
  "response": {"ok": true},
  "error": null
}
```

**Implementation**:
```python
# In every service main.py
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": SERVICE_NAME,
            "correlation_id": record.correlation_id,
            "message": record.getMessage(),
            "duration_ms": getattr(record, "duration_ms", None),
            "error": record.exc_info if record.exc_info else None
        }
        return json.dumps(log_data)

handler = logging.FileHandler(f"S:\logs\services\{SERVICE_NAME}.log")
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
```

#### 5.2 Unified Error Codes
**Standard codes across all services**:
```
OK (200)
INVALID_ARGUMENT (400) - Bad request parameter
UNAUTHORIZED (401) - Missing/invalid auth
FORBIDDEN (403) - Policy denied
NOT_FOUND (404) - Resource not found
CONFLICT (409) - Resource already exists
TIMEOUT (408) - Operation timed out
UNAVAILABLE (503) - Dependency down
INTERNAL_ERROR (500) - Unhandled exception
DEGRADED (200 with warning) - Service partially working
```

#### 5.3 Service Dashboard
```
┌─────────────────────────────────────────────────┐
│ SONIA PRODUCTION DASHBOARD                      │
├─────────────────────────────────────────────────┤
│ Uptime: 48d 3h 12m                              │
│ Error Rate: 0.02%  (green)                      │
│ p95 Latency: 234ms  (green)                     │
├─────────────────────────────────────────────────┤
│ API Gateway (7000)                              │
│   Status: OK  Errors: 0  p95: 145ms             │
│   Requests: 24,534  Memory: 234 MB              │
│                                                  │
│ Memory Engine (7020)                            │
│   Status: OK  Errors: 0  p95: 89ms              │
│   Searches: 12,234  Memory: 456 MB              │
│                                                  │
│ Pipecat (7030)                                  │
│   Status: OK  Errors: 0  p95: 234ms             │
│   Sessions: 12  Active: 3  Memory: 312 MB       │
│                                                  │
│ OpenClaw (7040)                                 │
│   Status: OK  Errors: 0  p95: 78ms              │
│   Executions: 5,234  Memory: 178 MB             │
│                                                  │
│ EVA-OS (7050)                                   │
│   Status: OK  Errors: 0  p95: 34ms              │
│   Approvals: 234  Memory: 89 MB                 │
│                                                  │
│ Model Router (7010)                             │
│   Status: OK  Errors: 0  p95: 1234ms            │
│   Requests: 5,234  Memory: 567 MB               │
├─────────────────────────────────────────────────┤
│ Alerts: None                                    │
│ Next backup: 2026-02-08 15:00:00               │
└─────────────────────────────────────────────────┘
```

#### 5.4 Alert Thresholds
```
CRITICAL (page on-call):
  - Any service: status != OK
  - Error rate > 5%
  - p95 latency > 5000ms
  - Memory growth > 100MB/hour
  - Disk usage > 90%

WARNING (create ticket):
  - Error rate > 1%
  - p95 latency > 2000ms
  - Memory growth > 50MB/hour
  - Service restart detected

INFO (log, no alert):
  - Error rate < 1%
  - All latencies < 2000ms
  - Memory stable
  - No restarts
```

### Pass Criteria
- ✅ JSON logs produced by all services
- ✅ Unified error codes in all responses
- ✅ Dashboard template created (mockup or real)
- ✅ Alert thresholds defined
- ✅ Correlation IDs flowing through all services
- ✅ Log aggregation script ready

---

## GATE 6: Release Process Lock

### Objective
Tag the release candidate and establish sign-off process.

### Execution

**Tag release candidate**:
```bash
cd S:\
git tag -a release-candidate-1 -m "Phase 3 GO/NO-GO candidate"
git tag -a release-v1.0.0-rc1 -m "Production candidate build"
```

**Release checklist** (S:\RELEASE_CHECKLIST.md):
```
MANDATORY SIGN-OFFS REQUIRED:

[ ] Go/No-Go Gate Results
    - Report: S:\artifacts\phase3\go-no-go-summary-*.json
    - Passed by: _________  Date: _________

[ ] Reliability Soak (48 hours)
    - Metrics: S:\artifacts\phase3\soak-metrics-*.json
    - Error rate < 0.5%: YES [ ] NO [ ]
    - Memory stable: YES [ ] NO [ ]
    - No deadlocks: YES [ ] NO [ ]
    - Verified by: _________  Date: _________

[ ] Security Tests
    - Adversarial test report: S:\artifacts\phase3\security-tests.json
    - All 10+ tests passed: YES [ ] NO [ ]
    - Policy enforcement: YES [ ] NO [ ]
    - Auth tokens validated: YES [ ] NO [ ]
    - Verified by: _________  Date: _________

[ ] Data Durability Drill
    - Restore drill report: S:\artifacts\phase3\restore-drill.json
    - Backup executes: YES [ ] NO [ ]
    - Restore succeeds: YES [ ] NO [ ]
    - Data integrity verified: YES [ ] NO [ ]
    - Verified by: _________  Date: _________

[ ] Integration Tests
    - Latest run: S:\artifacts\phase3\integration-tests-final.json
    - Pass rate: 100% [ ] <100% [ ]
    - Deterministic: YES [ ] NO [ ]
    - Verified by: _________  Date: _________

RELEASE DECISION:
  Release Approved: [ ] YES [ ] NO
  
  Approved by: _________________ (Release Manager)
  Date: _________
  
  If NO, blockers:
  _________________________________
  _________________________________
```

**Artifact lock** (immutable evidence):
```
S:\artifacts\phase3\release-candidate-1\
├── go-no-go-summary.json       (Gate 1 results)
├── soak-metrics-final.json     (Gate 2 results)
├── security-tests.json         (Gate 3 results)
├── restore-drill.json          (Gate 4 results)
├── integration-tests.json      (Gate 5 results)
├── RELEASE_CHECKLIST.md        (Signed off)
└── MANIFEST.json               (What is released)
```

---

## Timeline

| Date | Phase | Gate | Status |
|------|-------|------|--------|
| 2026-02-08 | 3 | 1 (Go/No-Go) | EXECUTE TODAY |
| 2026-02-09 to 2026-02-11 | 3 | 2 (Soak 48h) | PENDING |
| 2026-02-11 to 2026-02-13 | 3 | 3 (Security) | PENDING |
| 2026-02-13 to 2026-02-14 | 3 | 4 (Durability) | PENDING |
| 2026-02-14 | 3 | 5 (Observability) | PENDING |
| 2026-02-15 | 3 | 6 (Release Lock) | PENDING |

---

## Success Criteria Summary

**Hard Gates** (must all pass):
- [ ] Gate 1: 10/10 cycles, 0 zombies, 360/360 health checks, deterministic tests
- [ ] Gate 2: Error rate < 0.5%, memory stable, no deadlocks
- [ ] Gate 3: All adversarial tests rejected, auth working, no policy bypasses
- [ ] Gate 4: Backup executes, restore succeeds, data integrity verified
- [ ] Gate 5: JSON logs, error codes, dashboard, alerts
- [ ] Gate 6: All sign-offs obtained, release candidate tagged

**Evidence Required**: Signed-off reports for each gate, immutable artifact bundle

**End Result**: `release-candidate-1` tagged and ready for production deployment

---

## Files to Create/Modify

### New Files
- [x] S:\scripts\testing\phase3-go-no-go.ps1 (DONE)
- [ ] S:\scripts\testing\phase3-soak-test.ps1
- [ ] S:\scripts\testing\phase3-security-tests.ps1
- [ ] S:\scripts\ops\backup-sonia-state.ps1
- [ ] S:\scripts\ops\restore-sonia-state.ps1
- [ ] S:\scripts\ops\preflight-checks.ps1
- [ ] S:\RELEASE_CHECKLIST.md
- [ ] S:\PHASE_3_EXECUTION_LOG.md

### Modified Files
- S:\services\*/main.py (add JSON logging, auth tokens)
- S:\config\sonia-config.json (add auth token secret)

---

## Next Action

Execute Gate 1 now:
```powershell
cd S:\scripts\testing
.\phase3-go-no-go.ps1 -CycleCount 10 -HealthCheckDurationMinutes 30
```

Await results. If PASS → Proceed to Gate 2 (48-hour soak). If FAIL → Root cause analysis.

---

**Phase 3 Status**: IN PROGRESS  
**Current Gate**: 1 (Go/No-Go) - Ready to execute  
**Target Release**: release-candidate-1 (2026-02-15)  
