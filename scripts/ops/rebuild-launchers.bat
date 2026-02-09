@echo off
setlocal

set "PS=C:\Program Files\PowerShell\7\pwsh.exe"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File S:\scripts\ops\rebuild-launchers.ps1

if errorlevel 1 (
  echo Rebuild failed
  exit /b 1
)

echo Rebuild complete
exit /b 0
