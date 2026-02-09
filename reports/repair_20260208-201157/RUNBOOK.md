# SONIA Runbook

## Prerequisites
- Windows 11 with PowerShell 5.1+
- Python environment at `S:\envs\sonia-core\python.exe`
- Ports 7000-7050 available

## 1. Environment Verification

```powershell
# Verify Python
& "S:\envs\sonia-core\python.exe" --version

# Verify key dependencies
& "S:\envs\sonia-core\python.exe" -c "import fastapi, uvicorn, pydantic, httpx; print('OK')"

# Verify shared library loads
powershell -NoProfile -Command ". S:\scripts\lib\sonia-stack.ps1; Get-SoniaRoot"
```

## 2. Pre-flight Checks

```powershell
# Check no services already running on SONIA ports
@(7000,7010,7020,7030,7040,7050) | ForEach-Object {
    $c = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
    if ($c) { Write-Host "PORT $_ IN USE by PID $($c.OwningProcess)" -ForegroundColor Red }
    else { Write-Host "PORT $_ available" -ForegroundColor Green }
}
```

## 3. Start Stack

```powershell
# Option A: Canonical launcher (recommended)
.\start-sonia-stack.ps1

# Option B: Individual services
. S:\scripts\lib\sonia-stack.ps1
Start-SoniaService -ServiceName "api-gateway" -ServiceDir "S:\services\api-gateway" -Port 7000
Start-SoniaService -ServiceName "model-router" -ServiceDir "S:\services\model-router" -Port 7010
Start-SoniaService -ServiceName "memory-engine" -ServiceDir "S:\services\memory-engine" -Port 7020
Start-SoniaService -ServiceName "pipecat" -ServiceDir "S:\services\pipecat" -Port 7030
Start-SoniaService -ServiceName "openclaw" -ServiceDir "S:\services\openclaw" -Port 7040
Start-SoniaService -ServiceName "eva-os" -ServiceDir "S:\services\eva-os" -Port 7050
```

## 4. Health Verification

```powershell
# Quick health check all services
@(
    @{Name="api-gateway";   Port=7000},
    @{Name="model-router";  Port=7010},
    @{Name="memory-engine"; Port=7020},
    @{Name="pipecat";       Port=7030},
    @{Name="openclaw";      Port=7040},
    @{Name="eva-os";        Port=7050}
) | ForEach-Object {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$($_.Port)/healthz" -TimeoutSec 3 -UseBasicParsing
        Write-Host "[OK] $($_.Name) :$($_.Port)" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $($_.Name) :$($_.Port)" -ForegroundColor Red
    }
}
```

## 5. Stop / Cleanup

```powershell
# Graceful stop
.\stop-sonia-stack.ps1

# Verify all stopped
@(7000,7010,7020,7030,7040,7050) | ForEach-Object {
    $c = Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue
    if ($c) { Write-Host "STILL RUNNING on port $_" -ForegroundColor Red }
}
```

## Log Locations
- Service stdout: `S:\logs\services\<name>.out.log`
- Service stderr: `S:\logs\services\<name>.err.log`
- PID files: `S:\state\pids\<name>.pid`

## Troubleshooting

**Service won't start:**
1. Check error log: `Get-Content S:\logs\services\<name>.err.log -Tail 30`
2. Check port in use: `Get-NetTCPConnection -LocalPort <port> -State Listen`
3. Kill stale process: `Stop-Process -Id <pid> -Force`

**Python not found:**
- Verify: `Test-Path S:\envs\sonia-core\python.exe`
- Reinstall env: `conda create --prefix S:\envs\sonia-core python=3.11 -y`
- Install deps: `& S:\envs\sonia-core\python.exe -m pip install fastapi uvicorn pydantic httpx aiohttp PyYAML`
