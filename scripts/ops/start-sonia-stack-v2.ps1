param(
    [switch]$SkipHealthCheck,
    [int]$StartupTimeoutSeconds = 90
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "S:\scripts\lib\sonia-stack.ps1"

$svc = @(
    @{name='api-gateway';  script='S:\scripts\ops\run-api-gateway.ps1';  port=7000},
    @{name='model-router'; script='S:\scripts\ops\run-model-router.ps1'; port=7010},
    @{name='memory-engine';script='S:\scripts\ops\run-memory-engine.ps1';port=7020},
    @{name='pipecat';      script='S:\scripts\ops\run-pipecat.ps1';      port=7030},
    @{name='openclaw';     script='S:\scripts\ops\run-openclaw.ps1';     port=7040},
    @{name='eva-os';       script='S:\scripts\ops\run-eva-os.ps1';       port=7050}
)

Write-Host "[SONIA] Starting Sonia Stack..."
Write-Host "[SONIA] Root: S:\"

$failedCount = 0
foreach ($s in $svc) {
    try {
        Write-Host "[SONIA] Starting $($s.name)..."
        $servicePid = & $s.script
        if (-not $servicePid) { throw "No PID returned" }
        Write-Host "[SONIA] $($s.name) -> PID $servicePid"
    } catch {
        Write-Host "[ERROR] Failed to start $($s.name): $($_.Exception.Message)" -ForegroundColor Red
        $failedCount++
    }
}

if ($failedCount -gt 0) {
    Write-Host "[FATAL] $failedCount service(s) failed to start." -ForegroundColor Red
    exit 1
}

if (-not $SkipHealthCheck) {
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        $ok = 0
        foreach ($s in $svc) {
            if (Test-PortListen -Port $s.port) { $ok++ }
        }
        Write-Host ("[SONIA] Listening {0}/{1}" -f $ok, $svc.Count)
        if ($ok -eq $svc.Count) { break }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    if ($ok -ne $svc.Count) {
        Write-Host "[FATAL] Not all services listening: $ok/$($svc.Count)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "[OK] Sonia stack startup complete" -ForegroundColor Green
exit 0
