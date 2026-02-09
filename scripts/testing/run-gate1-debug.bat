@echo off
setlocal enabledelayedexpansion

REM Find PowerShell
set "PS_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "C:\Program Files\PowerShell\7\pwsh.exe" set "PS_EXE=C:\Program Files\PowerShell\7\pwsh.exe"

if not exist "!PS_EXE!" (
  echo ERROR: PowerShell not found at !PS_EXE!
  exit /b 9009
)

cd /d S:\scripts\testing

REM Set environment and capture output
set PYTHONHASHSEED=0
set SONIA_TEST_MODE=deterministic

echo Executing Gate 1 with output to file...
"!PS_EXE!" -NoProfile -ExecutionPolicy Bypass -File "direct-gate1.ps1" > "S:\artifacts\phase3\gate1-execution-output.txt" 2>&1

set EXIT_CODE=!ERRORLEVEL!
echo EXIT_CODE=!EXIT_CODE!

if !EXIT_CODE! EQU 0 (
  echo Gate 1 PASSED
) else (
  echo Gate 1 FAILED with code !EXIT_CODE!
)

exit /b !EXIT_CODE!
