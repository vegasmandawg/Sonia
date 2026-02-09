@echo off
setlocal
cd /d "S:\scripts\testing"
set PYTHONHASHSEED=0
set SONIA_TEST_MODE=deterministic
powershell.exe -NoProfile -ExecutionPolicy Bypass -File phase3-preflight.ps1
exit /b %ERRORLEVEL%
