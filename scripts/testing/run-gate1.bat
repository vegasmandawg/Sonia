@echo off
REM Gate 1 Real Execution Runner - No Silent Failures
REM Enforces Evidence Mode: real execution output only, no simulation

setlocal enabledelayedexpansion

REM Find PowerShell executable
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "C:\Program Files\PowerShell\7\pwsh.exe" set "PS_EXE=C:\Program Files\PowerShell\7\pwsh.exe"

if not exist "!PS_EXE!" (
  echo ERROR: PowerShell executable not found at !PS_EXE!
  echo Checked locations:
  echo   - %SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe
  echo   - C:\Program Files\PowerShell\7\pwsh.exe
  exit /b 9009
)

echo [GATE1] Using PowerShell: !PS_EXE!

REM Change to test directory
cd /d S:\scripts\testing || (
  echo ERROR: Cannot change to S:\scripts\testing
  exit /b 2
)

REM Set deterministic environment
set "PYTHONHASHSEED=0"
set "SONIA_TEST_MODE=deterministic"
set "PATH=S:\tools\python;S:\tools\python\Scripts;!PATH!"

echo.
echo ===============================================
echo Phase 3 Gate 1 - Real Execution Runner
echo ===============================================
echo Timestamp: %DATE% %TIME%
echo PowerShell: !PS_EXE!
echo Environment: PYTHONHASHSEED=0, SONIA_TEST_MODE=deterministic
echo.

REM Precheck: verify Python and PowerShell
echo [PRECHECK] Verifying Python and PowerShell...
"!PS_EXE!" -NoProfile -ExecutionPolicy Bypass -Command "python --version; Write-Host 'PowerShell version:'; $PSVersionTable.PSVersion"
if errorlevel 1 (
  echo ERROR: Precheck failed
  exit /b %errorlevel%
)

echo.
echo [PREFLIGHT] Running service startup validation...
"!PS_EXE!" -NoProfile -ExecutionPolicy Bypass -File "S:\scripts\testing\phase3-preflight.ps1"
if errorlevel 1 (
  echo ERROR: Preflight validation failed
  exit /b %errorlevel%
)

echo.
echo [GATE1] Executing 10 cycles with real service startup/stop...
"!PS_EXE!" -NoProfile -ExecutionPolicy Bypass -File "S:\scripts\testing\phase3-go-no-go.ps1" -CycleCount 10 -HealthCheckDurationMinutes 30 -StartupTimeoutSeconds 90
if errorlevel 1 (
  echo ERROR: Gate 1 execution failed
  exit /b %errorlevel%
)

echo.
echo [SUCCESS] Gate 1 completed with real service execution
exit /b 0
