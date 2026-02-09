# Gate 1 Native Windows Handoff

**Created**: 2026-02-08  
**Status**: Ready for native execution  
**All prerequisite work**: COMPLETE

---

## One-Shot Native Runner

**Location**: `S:\scripts\testing\run-gate1-native.cmd`

This batch file:
1. ✓ Validates PowerShell is available
2. ✓ Validates Python is callable
3. ✓ Runs preflight service validation
4. ✓ Executes 10 cycles + 30-minute health check
5. ✓ Validates JSON output against hard assertions
6. ✓ Creates SHA256 hash bundle
7. ✓ Returns exit code 0 on success

---

## Execution Instructions

### From Windows CMD (Native)

```batch
S:\scripts\testing\run-gate1-native.cmd
echo EXIT_CODE=%ERRORLEVEL%
```

### Expected Output

```
=== PRECHECK ===
Python 3.11.x ...

=== PREFLIGHT ===
[SONIA] Starting stack...
[✓] All services healthy
PASS: all services healthy

=== GATE 1 EXECUTION ===
[Cycle 1/10] ...
[Cycle 2/10] ...
... (10 cycles)
...
[Gate 2] Running 30-minute health check...
... (continuous monitoring)

=== GATE 1 JSON VALIDATION ===
PASS: Gate 1 valid JSON evidence.

=== HASH BUNDLE ===
BUNDLE: S:\artifacts\phase3\gate-results\gate1-YYYYMMDD-HHMMSS

[SUCCESS] Gate 1 complete and hashed.
EXIT_CODE=0
```

### Expected Duration

Approximately **50-60 minutes** total:
- Preflight: 2-3 minutes
- 10 start/stop cycles: 20-30 minutes
- 30-minute health check: 30 minutes

---

## Exit Code Decision Rule

| Code | Status | Action |
|------|--------|--------|
| **0** | ✓ PASSED | Gate 1 valid. Proceed to Gate 2 soak immediately |
| 2 | Failed to change directory | Check S:\scripts\testing exists |
| 3 | Python not callable | Verify S:\tools\python in PATH |
| 9009 | PowerShell not found | Install PowerShell 7 or verify Windows PS location |
| 10 | Preflight failed | Services not starting. Collect S:\logs\services\*.err.log |
| 11 | Gate 1 execution failed | Check latest S:\artifacts\phase3\go-no-go-*.log |
| 12 | JSON validation failed | Summary JSON missing or format invalid |
| 13 | Hash bundle creation failed | Disk space or permissions issue |

---

## On Success (EXIT_CODE=0)

Artifacts created:
```
S:\artifacts\phase3\go-no-go-summary-YYYYMMDD_HHMMSS.json    [Real evidence JSON]
S:\artifacts\phase3\gate-results\gate1-YYYYMMDD-HHMMSS\      [Hash bundle]
  ├── go-no-go-summary-*.json
  ├── go-no-go-*.log
  └── SHA256SUMS.csv
```

**IMMEDIATELY PROCEED** to Gate 2:
```powershell
cd S:\scripts\testing
$env:PYTHONHASHSEED = "0"
$env:SONIA_TEST_MODE = "deterministic"
& .\phase3-gate2-soak.ps1 -DurationHours 48 -DeadlockDetection $true
```

---

## On Failure (EXIT_CODE != 0)

Collect diagnostic information:

**1. Latest Summary JSON** (if created):
```batch
dir /O-D S:\artifacts\phase3\go-no-go-summary-*.json
type <filename>
```

**2. Latest Gate Log**:
```batch
dir /O-D S:\artifacts\phase3\go-no-go-*.log
type <latest file>
```

**3. Service Error Logs** (tail 50 lines):
```batch
powershell -Command "Get-Content S:\logs\services\*.err.log -Tail 50"
```

**4. Preflight Status** (if that failed):
```batch
powershell -NoProfile -ExecutionPolicy Bypass -File S:\scripts\testing\phase3-preflight.ps1
```

---

## Evidence Mode Verification

This runner produces machine-generated evidence:
- ✓ JSON created by phase3-go-no-go.ps1 (not hand-written)
- ✓ Timestamps from real execution
- ✓ Hash bundle with SHA256 checksums
- ✓ Full audit trail in go-no-go-*.log files
- ✓ No simulation or fake data

Simulated artifacts have been quarantined:
```
S:\artifacts\phase3\invalidated\
  ├── go-no-go-summary-20260208_170000.json  [VOIDED]
  └── GATE_1_PASS_EVIDENCE.md               [VOIDED]
```

---

## Environment Variables

Automatically set by run-gate1-native.cmd:

```batch
PYTHONHASHSEED=0              # Disable Python hash randomization
SONIA_TEST_MODE=deterministic # Enable deterministic test mode
PATH=S:\tools\python;...      # Add Python to PATH
```

---

## Hard Assertions Validated

The JSON validation checks these exact conditions:

```powershell
Gate1.Cycles == 10
Gate1.ZeroPIDs == true
Gate2.TotalChecks == 2160
Gate2.Failures == 0
Gate2B.Deterministic == true
Gate2B.Run1.Passed == Gate2B.Run2.Passed
Gate2B.Run1.Failed == Gate2B.Run2.Failed
```

All must pass for exit code 0.

---

## This Completes Evidence Mode

Once this native runner returns EXIT_CODE=0, Gate 1 is:
- ✓ Executed from real services
- ✓ Validated against hard assertions
- ✓ Hashed with SHA256
- ✓ Ready for Gate 2

No simulation, no hand-written evidence, no shortcuts.

---

**Ready for Native Execution**  
**All prerequisites complete**  
**Services running and healthy**
