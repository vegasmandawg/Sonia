$ErrorActionPreference = "Stop"

$checks = @(
    @{ Name="api-gateway";   Url="http://127.0.0.1:7000/healthz" },
    @{ Name="model-router";  Url="http://127.0.0.1:7010/healthz" },
    @{ Name="memory-engine"; Url="http://127.0.0.1:7020/healthz" },
    @{ Name="pipecat";       Url="http://127.0.0.1:7030/healthz" },
    @{ Name="openclaw";      Url="http://127.0.0.1:7040/healthz" },
    @{ Name="eva-os";        Url="http://127.0.0.1:7050/healthz" }
)

$failed = @()
foreach ($c in $checks) {
    try {
        $r = Invoke-RestMethod -Uri $c.Url -TimeoutSec 5
        Write-Host "[OK]  $($c.Name) -> $($c.Url)"
    } catch {
        Write-Host "[FAIL] $($c.Name) -> $($c.Url)"
        $failed += $c.Name
    }
}

if ($failed.Count -gt 0) {
    Write-Error ("Health check failed: " + ($failed -join ", "))
    exit 1
}

Write-Host "All health checks passed."
exit 0
