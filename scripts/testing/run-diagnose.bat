@echo off
setlocal

set "PS=C:\Program Files\PowerShell\7\pwsh.exe"

"%PS%" -NoProfile -ExecutionPolicy Bypass -File S:\scripts\testing\diagnose-services.ps1
