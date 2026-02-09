# Phase 3 Gate Execution Prerequisites

**Mode**: Evidence (all checks must be completed and documented)  
**Status**: ⛔ **BLOCKING** - Prerequisites not yet satisfied  
**Blocker**: Python not in system PATH

---

## Critical Prerequisites (All Must Pass Before Gate 1)

### Prerequisite 1: Python Installation
**Status**: ❌ **FAILING**
```powershell
python --version
# Current: "python is not recognized"
# Required: Python 3.10+ 
```

**Fix Required**:
1. Download Python 3.10+ from https://www.python.org/downloads/
2. Run installer with "Add Python to PATH" checked
3. Verify: `python --version` returns version 3.10+

**Evidence Required**: Screenshot or log of `python --version` output

---

### Prerequisite 2: Pip and Dependencies
**Status**: ⏳ **PENDING Python installation**

**Required for each service**:
```powershell
cd S:\services\api-gateway
pip install -r requirements.lock

# Repeat for:
# - model-router
# - memory-engine  
# - pipecat
# - openclaw
# - eva-os
```

**Verification**:
```powershell
pip list | Select-String uvicorn
pip list | Select-String fastapi
# Both must be installed
```

**Evidence Required**: Output of `pip list` showing all required packages

---

### Prerequisite 3: Port State Verification
**Status**: ⏳ **PENDING**

**Verify ports 7000-7050 are free**:
```powershell
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -ge 7000 -and $_.LocalPort -le 7050 }
# Should return: (empty list)
```

**If ports are in use**:
```powershell
# Kill stale processes
Get-Process python | Stop-Process -Force
```

**Evidence Required**: Output showing ports are free

---

### Prerequisite 4: Directory Structure
**Status**: ✅ **VERIFIED**

**Required directories**:
```powershell
Test-Path S:\state\pids              # ✓ Exists
Test-Path S:\logs\services           # ✓ Exists
Test-Path S:\artifacts\phase3        # ✓ Exists
Test-Path S:\artifacts\phase3\evidence    # ✓ Created
Test-Path S:\artifacts\phase3\gate-results # ✓ Created
Test-Path S:\artifacts\phase3\manifests    # ✓ Created
```

**All exist**: ✅ Yes

---

### Prerequisite 5: Deterministic Environment Variables
**Status**: ✅ **PREPARED**

**Must be set before any gate execution**:
```powershell
$env:PYTHONHASHSEED = "0"          # Disable Python hash randomization
$env:SONIA_TEST_MODE = "deterministic"  # Force deterministic behavior
```

**Verification**:
```powershell
Write-Host $env:PYTHONHASHSEED     # Should output: 0
Write-Host $env:SONIA_TEST_MODE    # Should output: deterministic
```

**Note**: These are set in all gate execution scripts. No manual action required.

---

### Prerequisite 6: Service Scripts Validation
**Status**: ✅ **VERIFIED**

**Required scripts**:
```powershell
Test-Path S:\start-sonia-stack.ps1      # ✓ Exists
Test-Path S:\stop-sonia-stack.ps1       # ✓ Exists
Test-Path S:\scripts\ops\run-api-gateway.ps1  # ✓ Exists
Test-Path S:\scripts\testing\phase3-go-no-go.ps1  # ✓ Exists
Test-Path S:\scripts\testing\phase3-preflight.ps1 # ✓ Exists
```

**All exist**: ✅ Yes

---

### Prerequisite 7: BOOT_CONTRACT.md Lock
**Status**: ✅ **LOCKED**

**Contract Immutable**: Yes  
**Version**: bootable-1.0.0  
**May only be version-bumped with explicit approval**

**Current Service Ports**:
- API Gateway: 7000
- Model Router: 7010
- Memory Engine: 7020
- Pipecat: 7030
- OpenClaw: 7040
- EVA-OS: 7050

**No drift allowed**: ✓ Confirmed

---

### Prerequisite 8: Single Service Startup Test
**Status**: ⏳ **PENDING Python installation**

**Test procedure**:
```powershell
# Kill any existing Python processes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Start single service
cd S:\
.\scripts\ops\run-api-gateway.ps1

# In another PowerShell window, verify healthz
Invoke-WebRequest -Uri "http://127.0.0.1:7000/healthz" -TimeoutSec 2

# Expected response: StatusCode 200 + health JSON
# If successful: Service startup works

# Clean up
Get-Process python | Stop-Process -Force
```

**Evidence Required**: 
- Screenshot of healthz response with StatusCode 200
- No errors in `S:\logs\services\api-gateway.err.log`

---

### Prerequisite 9: Preflight Validator Execution
**Status**: ⏳ **PENDING all above**

**Test procedure**:
```powershell
cd S:\scripts\testing
$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"
.\phase3-preflight.ps1

# Expected exit code: 0 (success)
# Expected output: "PASS: all services healthy"
```

**If preflight fails**:
- STOP immediately
- Document failure in PHASE_3_EXECUTION_LOG.md
- Investigate error logs
- Fix root cause
- Re-run preflight

**Evidence Required**:
- Preflight execution log
- Exit code (must be 0)
- All 6 services detected as UP

---

### Prerequisite 10: RELEASE_CHECKLIST.md Prepared
**Status**: ✅ **PREPARED**

**File location**: `S:\RELEASE_CHECKLIST.md`  
**Contents**: Gate sign-off matrix with all 5 gates listed  
**Ready for**: Population with evidence after each gate passes

---

## Prerequisite Checklist

### Before Gate 1 Execution

- [ ] Python 3.10+ installed in PATH (`python --version` returns 3.10+)
- [ ] All 6 services' requirements.lock installed via pip
- [ ] Ports 7000-7050 verified free
- [ ] Single service (API Gateway) starts successfully with healthz=200
- [ ] Preflight validator executed and passes (exit code 0)
- [ ] Environment variables set: PYTHONHASHSEED=0, SONIA_TEST_MODE=deterministic
- [ ] All required directories exist
- [ ] BOOT_CONTRACT.md is locked and immutable
- [ ] PHASE_3_EXECUTION_LOG.md created with daily cadence
- [ ] Evidence framework in place: `S:\artifacts\phase3\evidence\`, `gate-results\`, `manifests\`

---

## Blocker Resolution

**Current Blocker**: Python not in system PATH

**Resolution Steps**:
1. Download Python 3.10+ from https://www.python.org/downloads/
2. Run installer on Windows
3. Check "Add Python to PATH" during installation
4. Restart PowerShell session
5. Verify: `python --version`
6. Document completion in PHASE_3_EXECUTION_LOG.md

**Timeline to Unblock**: ~15-30 minutes (download + install + verify)

---

## No-Go Criteria

**Do NOT proceed to Gate 1 if**:
- [ ] Python is not in PATH
- [ ] Single service startup fails
- [ ] Preflight validator fails
- [ ] Any required directory is missing
- [ ] BOOT_CONTRACT.md has drifted
- [ ] Environment variables cannot be set

---

## Execution Readiness

**Current Status**: ⛔ **NOT READY**  
**Blocker**: Python installation required

**Next Action**: Install Python 3.10+, then proceed with prerequisites 2-10

**Gate 1 can only start after all prerequisites are satisfied and documented**

---

## Evidence Documentation

Once prerequisites are complete, document in `S:\artifacts\phase3\evidence\`:
```
PREREQUISITES_COMPLETED_TIMESTAMP.txt
├── Python version: 3.10.x
├── Pip version: 23.x
├── Services dependencies: All installed
├── Ports verified: Free (7000-7050)
├── Single service test: PASS
├── Preflight validator: PASS (exit 0)
├── Environment variables: Set
├── BOOT_CONTRACT.md: Locked
└── Timestamp: 2026-02-DD HH:MM:SS
```

---

**Status**: Prerequisites NOT MET - Python installation required  
**Timeline**: ~30 minutes to unblock + prerequisites validation  
**Next Update**: After Python installation and single service test
