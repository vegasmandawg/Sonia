# Release Checklist - release-candidate-1

**Release Name**: release-candidate-1  
**Target Date**: 2026-02-15  
**Release Manager**: _________________  
**Status**: PENDING  

---

## Hard Blocking Gate 1: Go/No-Go Startup Reliability

**Requirement**: 10 consecutive start/stop cycles with 0 failures

**Execution Command**:
```powershell
cd S:\scripts\testing
.\phase3-go-no-go.ps1 -CycleCount 10 -HealthCheckDurationMinutes 30
```

**Expected Results**:
```
✓ 10/10 cycles successful (100% pass rate)
✓ 0 zombie PIDs after each stop
✓ 2,160/2,160 health checks passed (360 intervals × 6 services)
  - 30 minutes = 360 intervals (every 5 seconds)
  - 6 services per interval (ports 7000, 7010, 7020, 7030, 7040, 7050)
  - Total: 360 × 6 = 2,160 individual checks required
  - Failure threshold: ANY check fails = gate fails
✓ 2x deterministic integration test runs (identical results)
  - Run 1 result MUST EQUAL Run 2 result exactly
  - Same pass count, same fail count, same tests passing
✓ Release artifact bundle captured
```

**Evidence Location**: `S:\artifacts\phase3\go-no-go-summary-*.json`

**Sign-Off**:
- [ ] Test executed successfully
- [ ] All gates passed (0 failures)
- [ ] Artifact bundle verified
- [ ] Log reviewed for anomalies

**Signed By**: _________________ **Date**: _________ **Result**: [ ] PASS [ ] FAIL

---

## Hard Blocking Gate 2: 48-Hour Reliability Soak

**Requirement**: Continuous synthetic traffic with error rate < 0.5%

**Traffic Profile**:
```
- /v1/chat: 1 req/sec steady (720 req/hour)
- /v1/action: OpenClaw executions (6 per soak interval)
- /session/start+stop: Voice session churn (5 per interval)
- Correlation IDs: All requests include X-Correlation-ID
```

**Execution Command**:
```powershell
# Prerequisite: Gate 1 must PASS
cd S:\scripts\testing
.\phase3-soak-test.ps1 -Duration 48
# This will run for 48 hours, collecting metrics every 60 seconds
```

**Expected Results**:
```
✓ Error rate < 0.5% (hard requirement)
✓ No unbounded memory growth (stabilizes after warm-up)
✓ No deadlocks or stuck sessions
✓ No service restarts
✓ p95 latency stable (not trending upward)
```

**Metrics to Review**:
- Error rate trend (must stay below 0.5%)
- Memory usage (should plateau)
- P95 latency (should stabilize)
- Service restart count (must be 0)

**Evidence Location**: `S:\artifacts\phase3\soak-metrics-*.csv` and `soak-summary-*.json`

**Sign-Off**:
- [ ] Soak executed for full 48 hours
- [ ] Error rate < 0.5% verified
- [ ] Memory stable (no unbounded growth)
- [ ] No deadlocks or stuck sessions
- [ ] Metrics file reviewed

**Signed By**: _________________ **Date**: _________ **Result**: [ ] PASS [ ] FAIL

---

## Hard Blocking Gate 3: Security & Safety Hardening

**Requirement**: All adversarial tests rejected, server-side policy enforcement

### 3A: Internal Service Authentication

**Test**: All inter-service calls validate auth tokens

**Checklist**:
- [ ] Bearer token issued by EVA-OS on startup
- [ ] Token included in all API Gateway → Memory/Router/OpenClaw calls
- [ ] Token validation on every request (not just first)
- [ ] Invalid token → 401 Unauthorized
- [ ] No client-side trust

**Evidence**:
- [ ] Code review: API Gateway clients include X-Service-Token header
- [ ] Code review: Each service validates token on startup
- [ ] Test: curl with missing token → 401
- [ ] Test: curl with invalid token → 401
- [ ] Test: curl with valid token → 200

### 3B: Tool Policy Enforcement (Server-Side Only)

**Test**: Destructive tools require EVA-OS approval, enforced server-side

**Adversarial Tests** (all must be REJECTED):

1. **Direct tool execution without approval**
   ```bash
   curl -X POST http://localhost:7040/execute \
     -H "Content-Type: application/json" \
     -d '{"tool_name":"shell.run","args":{"command":"rm /important/file"}}'
   ```
   Expected: 403 Forbidden (POLICY_DENIED)

2. **Spoofed approval token**
   ```bash
   curl -X POST http://localhost:7040/execute \
     -H "Content-Type: application/json" \
     -d '{"tool_name":"shell.run","args":...,"approval_token":"fake"}'
   ```
   Expected: 401 Unauthorized (INVALID_APPROVAL)

3. **Approval token from different tool**
   ```
   1. Get approval for tool A
   2. Use token to execute tool B
   ```
   Expected: 401 (token scope violation)

**Checklist**:
- [ ] All 10+ adversarial tests executed
- [ ] All tests rejected with correct error codes
- [ ] Error messages don't leak sensitive info
- [ ] Approval workflow enforced end-to-end

**Evidence Location**: `S:\artifacts\phase3\security-tests.json`

### 3C: Command Allowlist & Path Sandboxing

**Test**: Blocked commands and path traversal attacks

**Adversarial Tests**:

1. **Directory change attempt**
   ```bash
   curl -X POST http://localhost:7040/execute \
     -d '{"tool_name":"shell.run","args":{"command":"cd /tmp && malware.exe"}}'
   ```
   Expected: 400 (INVALID_COMMAND)

2. **Path traversal**
   ```bash
   curl -X POST http://localhost:7040/execute \
     -d '{"tool_name":"file.read","args":{"path":"../../../../etc/passwd"}}'
   ```
   Expected: 403 (PATH_OUTSIDE_SANDBOX)

3. **Symlink attack**
   ```bash
   curl -X POST http://localhost:7040/execute \
     -d '{"tool_name":"file.read","args":{"path":"S:/data/link-to-secret"}}'
   ```
   Expected: 403 (SYMLINK_DENIED)

**Checklist**:
- [ ] Allowlist enforced (only whitelisted commands allowed)
- [ ] Path sandboxing working (paths normalized, traversal blocked)
- [ ] Symlink detection active
- [ ] All adversarial commands rejected

### 3D: Secrets & Config Validation

**Preflight Checks** (run before startup):
```powershell
.\scripts\ops\preflight-checks.ps1
```

Expected:
```
✓ No hardcoded secrets in config
✓ All required env vars set
✓ Policy files syntax valid
✓ File permissions correct (no world-readable secrets)
✓ Service certificates valid (if using mTLS)
```

**Checklist**:
- [ ] Secrets scan passes (0 hardcoded secrets)
- [ ] Config validation passes
- [ ] Permissions check passes
- [ ] Preflight script runs before startup

**Evidence Location**: `S:\artifacts\phase3\preflight-check.json`

**Overall Sign-Off**:
- [ ] All 4 security gates passed
- [ ] No policy bypasses found
- [ ] Server-side enforcement verified
- [ ] Adversarial tests all rejected

**Signed By**: _________________ **Date**: _________ **Result**: [ ] PASS [ ] FAIL

---

## Hard Blocking Gate 4: Data Durability & Recovery

**Requirement**: Backup/restore drill succeeds end-to-end

### 4A: Backup Execution

```powershell
.\scripts\ops\backup-sonia-state.ps1 -BackupDir "S:\backups\phase3-validation"
```

**Checklist**:
- [ ] Backup script completes without error
- [ ] All required files captured:
  - [ ] SQLite database (S:\data\memory\*.db)
  - [ ] Session state (S:\data\sessions\*.json)
  - [ ] Configuration (S:\config\sonia-config.json)
  - [ ] Policy files (S:\config\policies\*.json)
- [ ] Backup is readable (not corrupted)
- [ ] Backup size is reasonable (< 5GB)

### 4B: Restore to Clean Copy

```powershell
# 1. Clone fresh S:\ to S:\test-restore\
# 2. Delete data in fresh copy
# 3. Restore from backup
.\scripts\ops\restore-sonia-state.ps1 `
  -BackupDir "S:\backups\phase3-validation" `
  -TargetDir "S:\test-restore"

# 4. Start fresh copy
cd S:\test-restore\
.\start-sonia-stack.ps1

# 5. Verify data intact
curl http://localhost:7020/search -d '{"query":"test"}'
```

**Checklist**:
- [ ] Restore completes without error
- [ ] Services start successfully post-restore
- [ ] Health checks pass
- [ ] Memory search returns pre-backup data
- [ ] Session state recovered

### 4C: WAL Consistency & Index Validation

```python
import sqlite3

# Verify database integrity
conn = sqlite3.connect("S:\data\memory\sonia.db")
cursor = conn.cursor()
cursor.execute("PRAGMA integrity_check")
result = cursor.fetchone()
assert result[0] == "ok", f"Database corruption: {result}"

# Rebuild indexes if needed
cursor.execute("REINDEX")
```

**Checklist**:
- [ ] SQLite integrity check passes
- [ ] No WAL corruption detected
- [ ] Indexes rebuilt successfully
- [ ] Database queries return correct results

### 4D: RPO/RTO Documentation

Document in `S:\RUNTIME_CONTRACT.md`:

```
RPO (Recovery Point Objective): 6 hours
  - Backups run every 6 hours
  - Maximum data loss: 6 hours of operations
  - Sessions: Lost (user-created)

RTO (Recovery Time Objective): 8 minutes
  - Backup restore: 5 minutes
  - Service startup: 2 minutes
  - Health verification: 1 minute

Failure Scenarios:
  1. Single service crash → Container restart (< 1 min)
  2. Disk full → Secondary disk backup (< 5 min)
  3. Data corruption → Restore from backup (< 8 min)
  4. Operator mistake → Git reset (< 2 min)
```

**Checklist**:
- [ ] RPO/RTO defined and documented
- [ ] Acceptable for production use
- [ ] Recovery scenarios documented
- [ ] Runbook available for each scenario

**Overall Sign-Off**:
- [ ] Backup executes
- [ ] Restore succeeds
- [ ] Data integrity verified
- [ ] WAL consistency validated
- [ ] RPO/RTO documented and acceptable

**Signed By**: _________________ **Date**: _________ **Result**: [ ] PASS [ ] FAIL

---

## Hard Blocking Gate 5: Integration Test Determinism

**Requirement**: Integration tests pass 100%, deterministic across runs

**Execution**:
```powershell
cd S:\tests\integration
python -m pytest test_phase2_e2e.py -v --tb=short
# Must run successfully with no flaky tests
```

**Checklist**:
- [ ] Integration suite passes 100%
- [ ] No test timeouts
- [ ] No race conditions
- [ ] Results reproducible (same results on repeat runs)
- [ ] All 40+ test cases covered

**Test Categories**:
- [ ] API Gateway chat orchestration (5+ tests)
- [ ] API Gateway action execution (5+ tests)
- [ ] Memory Engine search (5+ tests)
- [ ] Pipecat session lifecycle (5+ tests)
- [ ] WebSocket communication (5+ tests)
- [ ] Correlation ID propagation (5+ tests)
- [ ] Standard envelope compliance (5+ tests)
- [ ] Error handling (5+ tests)

**Evidence Location**: `S:\artifacts\phase3\integration-tests-final.json`

**Sign-Off**:
- [ ] Tests executed
- [ ] 100% pass rate
- [ ] No flaky tests
- [ ] Deterministic results
- [ ] All categories covered

**Signed By**: _________________ **Date**: _________ **Result**: [ ] PASS [ ] FAIL

---

## Post-Gate Activity: Release Ceremony (Non-Gate)

**This is NOT a gate** - this is the final step after all 5 gates pass.

### Release Ceremony Steps
1. Tag release-candidate-1 in git
2. Create immutable artifact bundle
3. Obtain all required sign-offs
4. Document final evidence

**No pass criteria** - this is administrative

---

## Observability & Documentation (Non-Blocking, Info)

### 5A: JSON Logging

**Checklist**:
- [ ] All services produce JSON-structured logs
- [ ] Logs include: timestamp, level, service, correlation_id, duration_ms
- [ ] Logs written to S:\logs\services\{service}.log
- [ ] Log rotation configured

### 5B: Error Codes

**Checklist**:
- [ ] Standard error codes in use (OK, INVALID_ARGUMENT, TIMEOUT, etc.)
- [ ] Error codes documented in BOOT_CONTRACT.md
- [ ] All responses follow envelope format

### 5C: Monitoring Dashboard

**Checklist**:
- [ ] Dashboard template created (S:\DASHBOARD.md)
- [ ] Shows: uptime, error rate, p95 latency, session count, memory
- [ ] Alert thresholds defined
- [ ] Grafana/Prometheus ready (optional)

**Evidence Location**: `S:\DASHBOARD.md` and `S:\ALERT_THRESHOLDS.md`

---

## Release Decision

**All Hard Blocking Gates Status**:

| Gate | Required | Status | Evidence | Signed Off |
|------|----------|--------|----------|-----------|
| Go/No-Go Startup | ✓ PASS | [ ] PASS [ ] FAIL | S:\artifacts\phase3\*.json | [ ] |
| 48-Hour Soak | ✓ PASS | [ ] PASS [ ] FAIL | S:\artifacts\phase3\soak-*.csv | [ ] |
| Security Tests | ✓ PASS | [ ] PASS [ ] FAIL | S:\artifacts\phase3\security-tests.json | [ ] |
| Data Durability | ✓ PASS | [ ] PASS [ ] FAIL | S:\artifacts\phase3\restore-drill.json | [ ] |
| Integration Tests | ✓ PASS | [ ] PASS [ ] FAIL | S:\artifacts\phase3\integration-tests.json | [ ] |

**Final Release Decision**:

```
Prerequisites Met:
  [ ] All 5 hard blocking gates: PASS
  [ ] All evidence artifacts present
  [ ] All sign-offs obtained
  [ ] No critical bugs found during gates

RELEASE APPROVED FOR PRODUCTION: [ ] YES  [ ] NO

If NO, blocking issues:
_________________________________
_________________________________
_________________________________

Release Manager: _________________ Date: _________

Approved by Director/VP: _________________ Date: _________
```

---

## Post-Release (GA)

Once released to production:

- [ ] Tag git: `git tag -a v1.0.0 -m "Production GA release"`
- [ ] Create release notes: `S:\RELEASE_NOTES_v1.0.0.md`
- [ ] Publish deployment guide: `S:\DEPLOYMENT_GUIDE.md`
- [ ] Notify operations team
- [ ] Begin SLA monitoring

---

**Checklist Version**: 1.0  
**Last Updated**: 2026-02-08  
**Status**: READY FOR EXECUTION  
