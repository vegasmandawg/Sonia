$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$out = @()
$out += "=== SNAPSHOT TEST ==="

try {
    $BaselineFile = "S:\artifacts\phase3\soak\t0-baseline.json"
    $Baseline = Get-Content $BaselineFile -Raw | ConvertFrom-Json
    $out += "Baseline loaded OK"

    $ServiceSpec = @(
        @{ Name="api-gateway"; Port=7000; Pid="S:\state\pids\api-gateway.pid" }
    )

    $svc = $ServiceSpec[0]

    # Test PID extraction
    $currentPID = $null
    if (Test-Path $svc.Pid) {
        $currentPID = [int](Get-Content $svc.Pid -ErrorAction Stop | Select-Object -First 1)
        $out += "Current PID: $currentPID"
    }

    # Test baseline PID access
    $out += "Baseline pids type: $($Baseline.pids.GetType().Name)"
    $out += "Baseline pids keys:"
    $Baseline.pids.PSObject.Properties | ForEach-Object { $out += "  $($_.Name) = $($_.Value)" }

    $baselinePID = $Baseline.pids.($svc.Name)
    $out += "Baseline PID for api-gateway: $baselinePID"
    $out += "PID Match: $($currentPID -eq $baselinePID)"

    # Test metrics access
    $out += "Baseline metrics type: $($Baseline.metrics.GetType().Name)"
    $out += "Baseline metrics count: $($Baseline.metrics.Count)"

    # This is the likely failure point - Where-Object on deserialized JSON
    $baselineEntry = $Baseline.metrics | Where-Object { $_.Name -eq $svc.Name }
    $out += "Baseline entry: $($baselineEntry | ConvertTo-Json -Compress)"

    $baselineRSS = $baselineEntry.RSS_KB
    $out += "Baseline RSS: $baselineRSS"

    # Test health check
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:7000/healthz" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    $out += "Healthz: $($resp.StatusCode)"

    # Test log burst
    $logFiles = @(Get-ChildItem "S:\logs\services\*.err.log" -ErrorAction SilentlyContinue)
    $out += "Error log files: $($logFiles.Count)"

    # Test config drift
    if (Test-Path "S:\config\sonia-config.json") {
        $hash = (Get-FileHash -LiteralPath "S:\config\sonia-config.json" -Algorithm SHA256).Hash
        $out += "Current config hash: $hash"
        $out += "Drift: $($hash -ne $Baseline.config_hash)"
    } else {
        $out += "Config file not found"
    }

    $out += "ALL TESTS PASSED"
} catch {
    $out += "ERROR: $($_.Exception.Message)"
    $out += "Line: $($_.InvocationInfo.ScriptLineNumber)"
    $out += "Stack: $($_.ScriptStackTrace)"
}

$out | Out-File -FilePath "S:\artifacts\phase3\soak\snapshot-test.txt" -Encoding UTF8
