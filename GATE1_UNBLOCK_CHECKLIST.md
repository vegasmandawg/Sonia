# Gate 1 Unblock Checklist

**Current Status**: BLOCKED - Services fail to start  
**Blocker**: Python not available or dependencies not installed  
**Goal**: Get services running so hard block validation can proceed

---

## Step 1: Verify Python Installation

### [ ] Check if Python is available
```powershell
python --version
# Expected output: Python 3.10.x, 3.11.x, 3.12.x, etc.
```

**If missing**:
- Download from https://www.python.org/ (3.10+)
- Install with "Add Python to PATH" checked
- Verify: `python --version`

**If venv needed**:
```powershell
# Create virtual environment
python -m venv S:\venv

# Activate it (Windows)
S:\venv\Scripts\Activate.ps1

# You should see (venv) at start of PowerShell prompt
```

### [ ] Verify pip works
```powershell
pip --version
# Expected: pip X.Y.Z from ...
```

---

## Step 2: Install Dependencies

### [ ] API Gateway dependencies
```powershell
cd S:\services\api-gateway
pip install -r requirements.lock

# Verify uvicorn installed:
uvicorn --version
```

### [ ] Model Router dependencies
```powershell
cd S:\services\model-router
pip install -r requirements.lock
```

### [ ] Memory Engine dependencies
```powershell
cd S:\services\memory-engine
pip install -r requirements.lock
```

### [ ] Pipecat dependencies
```powershell
cd S:\services\pipecat
pip install -r requirements.lock
```

### [ ] OpenClaw dependencies
```powershell
cd S:\services\openclaw
pip install -r requirements.lock
```

### [ ] EVA-OS dependencies
```powershell
cd S:\services\eva-os
pip install -r requirements.lock
```

**Note**: If any service doesn't have requirements.lock, check for requirements.txt or pyproject.toml

---

## Step 3: Verify Individual Service Startup

### [ ] Test API Gateway startup
```powershell
cd S:\
.\scripts\ops\run-api-gateway.ps1

# Wait 5 seconds, then in another PowerShell:
Invoke-WebRequest -Uri "http://127.0.0.1:7000/healthz" -TimeoutSec 2

# Expected: StatusCode 200, Content shows health status
# If error: Check S:\logs\services\api-gateway.err.log
```

### [ ] Kill test process
```powershell
Get-Process python | Stop-Process -Force
```

### [ ] Test Model Router startup
```powershell
cd S:\
.\scripts\ops\run-model-router.ps1

# In another PowerShell:
Invoke-WebRequest -Uri "http://127.0.0.1:7010/healthz" -TimeoutSec 2

# Kill:
Get-Process python | Stop-Process -Force
```

### [ ] Test remaining services similarly
```powershell
# Test each of these the same way:
# - Memory Engine (port 7020): .\scripts\ops\run-memory-engine.ps1
# - Pipecat (port 7030): .\scripts\ops\run-pipecat.ps1
# - OpenClaw (port 7040): .\scripts\ops\run-openclaw.ps1
# - EVA-OS (port 7050): .\scripts\ops\run-eva-os.ps1
```

---

## Step 4: Clean Port State

### [ ] Verify ports are free
```powershell
# Check if any processes are using ports 7000-7050
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -ge 7000 -and $_.LocalPort -le 7050 }

# If any found, kill them:
Get-Process | Where-Object { $_.Id -eq <PID> } | Stop-Process -Force
```

### [ ] Clean PID directory
```powershell
# Remove stale PID files
Remove-Item -Path S:\state\pids\*.pid -Force -ErrorAction SilentlyContinue

# Create fresh directory
New-Item -ItemType Directory -Path S:\state\pids -Force | Out-Null
```

---

## Step 5: Re-Run Gate 1 (Single Cycle Test)

### [ ] Single cycle test
```powershell
cd S:\scripts\testing

# Set environment
$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"

# Run single cycle (quick validation)
.\phase3-go-no-go.ps1 -CycleCount 1 -StartupTimeoutSeconds 90

# Expected output should show:
# [PASS] - Cycle 1: All services healthy
# [SUMMARY] Cycles passed: 1/1
# [PASS] GATE 1 PASSED (for single cycle)
```

### [ ] Check for errors
```powershell
# If failed, check diagnostics:
Get-Content S:\artifacts\phase3\gate1-*.log -Tail 50
Get-Content S:\logs\services\api-gateway.err.log -Tail 20
```

---

## Step 6: Full Gate 1 Execution

### [ ] Once single cycle passes, run full 10 cycles
```powershell
cd S:\scripts\testing

$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"

# This will take ~5 minutes
.\phase3-go-no-go.ps1 -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
```

### [ ] Verify success
```powershell
# Check for JSON output
Get-Item S:\artifacts\phase3\go-no-go-summary-*.json

# Read the summary
Get-Content S:\artifacts\phase3\go-no-go-summary-*.json | ConvertFrom-Json

# Should show:
# Status: PASSED
# GateCounts.Gate1.Cycles: 10
# GateCounts.Gate1.Total: 10
# GateCounts.Gate1.ZeroPIDs: true
```

---

## Step 7: Continue to Gate 2 (If Gate 1 Passed)

### [ ] Gate 1 successful?
- [ ] All 10 cycles completed
- [ ] All healthz checks passed
- [ ] No zombie processes
- [ ] JSON evidence file created

### [ ] Proceed to Gate 2
```powershell
# Script will automatically continue after Gate 1 passes
# Expected to run: 30-minute health check soak
# Verifies: 2,160 health checks with 0 failures
```

---

## Expected Timeline

| Step | Task | Time |
|------|------|------|
| 1 | Python verification | 2 min |
| 2 | Dependency installation | 15-30 min |
| 3 | Individual service tests | 5-10 min |
| 4 | Port cleanup | 2 min |
| 5 | Single cycle test | 1-2 min |
| 6 | Full Gate 1 (10 cycles) | 5 min |
| 7 | Gate 2 (if Gate 1 passes) | 35 min |

**Total to complete Gates 1-2**: ~60-90 minutes

---

## Troubleshooting

### Python not found
```powershell
# Option 1: Install globally from python.org
# Option 2: Use Windows Store: winget install Python.Python.3.12
# Option 3: Use Conda: conda install python=3.10
```

### ModuleNotFoundError: No module named 'uvicorn'
```powershell
# Run dependency install again
pip install -r requirements.lock

# Or install directly:
pip install uvicorn fastapi pydantic httpx
```

### Port already in use
```powershell
# Find and kill process using the port:
$proc = Get-NetTCPConnection -LocalPort 7000 -State Listen | ForEach-Object {Get-Process -Id $_.OwningProcess}
$proc | Stop-Process -Force
```

### Service starts but healthz times out
```powershell
# Check error logs:
Get-Content S:\logs\services\api-gateway.err.log -Tail 50

# Common issues:
# - Service requires environment variables (check main.py for uvicorn.run())
# - Service requires config file (check S:\config\sonia-config.json exists)
# - Service requires database (check if schema.sql exists and is initialized)
```

### Zombie processes after stop
```powershell
# Verify all killed:
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Check PID files are gone:
Get-Item S:\state\pids\*.pid | Remove-Item -Force
```

---

## Success Criteria

Once **all** of these are true, Gate 1 can pass:

- ✅ Python available in PATH
- ✅ All 6 service dependencies installed
- ✅ Single service startup works (port responds with 200)
- ✅ Ports 7000-7050 are free
- ✅ Single cycle test passes
- ✅ Full 10-cycle test passes
- ✅ JSON evidence file created with Status=PASSED
- ✅ No errors in error logs

---

## Reference: Hard Block Validation

Once services are running, Gate 1 hard block validates:

```
For each of 10 cycles:
  1. Start all services → check PID files created
  2. Verify process running → Get-Process matches PID
  3. Verify healthz responds → HTTP 200 on all ports
  4. Stop all services → processes terminate cleanly
  5. Verify zero zombies → all PIDs gone from OS

If ANY cycle fails: Gate 1 FAILS
If all 10 cycles pass: Gate 1 PASSES
```

**No mocking possible**: Real HTTP requests, real process verification, real port binding.

---

## When Blocked

If stuck on any step, check:
1. Error logs in `S:\logs\services\*.err.log`
2. Gate 1 execution log in `S:\artifacts\phase3\gate1-*.log`
3. PowerShell `$LASTEXITCODE` after running scripts
4. Stale processes: `Get-Process python -ErrorAction SilentlyContinue`

---

**Ready to unblock Gate 1? Start with Step 1 above.**
