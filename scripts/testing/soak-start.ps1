<#
.SYNOPSIS
Captures T0 baseline and starts the 48-hour soak.

.DESCRIPTION
1. Verifies stack is running and healthy
2. Captures T0 process metrics (PID, RSS, handles, threads)
3. Captures config hash
4. Writes t0-baseline.json
5. Launches soak-monitor.ps1 in background

.EXAMPLE
.\soak-start.ps1
#>

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SoakDir = "S:\artifacts\phase3\soak"
New-Item -ItemType Directory -Path $SoakDir -Force | Out-Null

$ServiceSpec = @(
    @{ Name="api-gateway"; Port=7000; Pid="S:\state\pids\api-gateway.pid" },
    @{ Name="model-router"; Port=7010; Pid="S:\state\pids\model-router.pid" },
    @{ Name="memory-engine"; Port=7020; Pid="S:\state\pids\memory-engine.pid" },
    @{ Name="pipecat"; Port=7030; Pid="S:\state\pids\pipecat.pid" },
    @{ Name="openclaw"; Port=7040; Pid="S:\state\pids\openclaw.pid" },
    @{ Name="eva-os"; Port=7050; Pid="S:\state\pids\eva-os.pid" }
)

Write-Host "`n=== SOAK T0 BASELINE CAPTURE ===" -ForegroundColor Cyan
Write-Host "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan

# Step 1: Verify all services healthy
Write-Host "`n--- Preflight: Health Check ---" -ForegroundColor Yellow
$allHealthy = $true
foreach ($svc in $ServiceSpec) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-Host "  [OK] $($svc.Name) :$($svc.Port)" -ForegroundColor Green
        } else {
            Write-Host "  [FAIL] $($svc.Name) :$($svc.Port) - status $($resp.StatusCode)" -ForegroundColor Red
            $allHealthy = $false
        }
    } catch {
        Write-Host "  [FAIL] $($svc.Name) :$($svc.Port) - $($_.Exception.Message)" -ForegroundColor Red
        $allHealthy = $false
    }
}

if (-not $allHealthy) {
    Write-Host "`n[FATAL] Not all services are healthy. Start the stack first." -ForegroundColor Red
    exit 1
}

# Step 2: Capture PIDs
Write-Host "`n--- Capturing PIDs ---" -ForegroundColor Yellow
$pids = @{}
foreach ($svc in $ServiceSpec) {
    if (Test-Path $svc.Pid) {
        $procId = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
        $pids[$svc.Name] = $procId
        Write-Host "  $($svc.Name) = PID $procId" -ForegroundColor DarkCyan
    } else {
        Write-Host "  [WARN] $($svc.Name) PID file missing" -ForegroundColor Yellow
        $pids[$svc.Name] = $null
    }
}

# Step 3: Capture process metrics
Write-Host "`n--- Capturing Process Metrics ---" -ForegroundColor Yellow
$metrics = @()
foreach ($svc in $ServiceSpec) {
    $procId = $pids[$svc.Name]
    if ($procId) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) {
            $m = @{
                Name = $svc.Name
                PID = $procId
                RSS_KB = [math]::Round($proc.WorkingSet64 / 1024)
                Handles = $proc.HandleCount
                Threads = $proc.Threads.Count
            }
            $metrics += $m
            Write-Host "  $($svc.Name): RSS=$($m.RSS_KB)KB Handles=$($m.Handles) Threads=$($m.Threads)" -ForegroundColor DarkCyan
        }
    }
}

# Step 4: Config hash
Write-Host "`n--- Config Hash ---" -ForegroundColor Yellow
if (Test-Path "S:\config\sonia-config.json") {
    $configHash = (Get-FileHash -LiteralPath "S:\config\sonia-config.json" -Algorithm SHA256).Hash
} else {
    $configHash = "NOT_FOUND"
}
Write-Host "  Config: $configHash" -ForegroundColor DarkCyan

# Step 5: Write baseline
$baseline = @{
    start_time = Get-Date -Format "o"
    config_hash = $configHash
    pids = $pids
    metrics = $metrics
    rc_manifest = "S:\artifacts\phase3\rc-1\SHA256SUMS.txt"
    soak_criteria = "S:\artifacts\phase3\soak\soak-criteria.json"
}

$baselineFile = Join-Path $SoakDir "t0-baseline.json"
$baseline | ConvertTo-Json -Depth 4 | Out-File -FilePath $baselineFile -Encoding UTF8

Write-Host "`n[OK] T0 baseline written: $baselineFile" -ForegroundColor Green
Write-Host ""
Write-Host "=== BASELINE SUMMARY ===" -ForegroundColor Cyan
Write-Host "  Services: 6/6 healthy" -ForegroundColor Green
Write-Host "  Config hash: $configHash" -ForegroundColor White
Write-Host "  PIDs captured: $($pids.Count)" -ForegroundColor White
Write-Host "  Metrics captured: $($metrics.Count) services" -ForegroundColor White
Write-Host ""
Write-Host "To start the soak monitor:" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File S:\scripts\testing\soak-monitor.ps1 -DurationHours 48" -ForegroundColor White
Write-Host ""
Write-Host "The monitor will run for 48 hours, taking snapshots every 15 min" -ForegroundColor Yellow
Write-Host "and checkpoints every 60 min. Aborts on any Sev-1/Sev-2 event." -ForegroundColor Yellow
