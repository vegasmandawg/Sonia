$ErrorActionPreference = "Stop"
$out = @()
$out += "=== SOAK DIAGNOSTIC ==="
$out += "Time: $(Get-Date)"

try {
    $BaselineFile = "S:\artifacts\phase3\soak\t0-baseline.json"
    $out += "Baseline exists: $(Test-Path $BaselineFile)"

    $raw = Get-Content $BaselineFile -Raw
    $out += "Baseline length: $($raw.Length)"

    $Baseline = $raw | ConvertFrom-Json
    $out += "Baseline parsed OK"
    $out += "Start time: $($Baseline.start_time)"
    $out += "Config hash: $($Baseline.config_hash)"
    $out += "PID count: $($Baseline.pids.PSObject.Properties.Count)"
    $out += "Metrics count: $($Baseline.metrics.Count)"

    # Try computing elapsed
    $T0 = [datetime]$Baseline.start_time
    $elapsed = [math]::Round(((Get-Date) - $T0).TotalHours, 2)
    $out += "Elapsed hours: $elapsed"

    # Try a health check
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:7000/healthz" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    $out += "api-gateway healthz: $($resp.StatusCode)"

    $out += "ALL CHECKS PASSED"
} catch {
    $out += "ERROR: $($_.Exception.Message)"
    $out += "At: $($_.ScriptStackTrace)"
}

$out | Out-File -FilePath "S:\artifacts\phase3\soak\diag-output.txt" -Encoding UTF8
