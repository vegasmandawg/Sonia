[CmdletBinding()]
param(
    [string]$Root = "S:\"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root.EndsWith("\")) { $Root = "$Root\" }

$targets = @(
    @{ Name = "api-gateway";  Url = "http://127.0.0.1:7000/health" },
    @{ Name = "model-router"; Url = "http://127.0.0.1:7010/health" },
    @{ Name = "memory-engine";Url = "http://127.0.0.1:7020/health" },
    @{ Name = "pipecat";      Url = "http://127.0.0.1:7030/health" },
    @{ Name = "openclaw";     Url = "http://127.0.0.1:7040/health" },
    @{ Name = "version";      Url = "http://127.0.0.1:7000/version" }
)

$results = New-Object System.Collections.Generic.List[object]
$failed = 0

foreach ($t in $targets) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-RestMethod -Uri $t.Url -Method Get -TimeoutSec 4
        $sw.Stop()
        $ok = $true
        if ($t.Name -ne "version" -and $resp.ok -ne $true) { $ok = $false }
        if (-not $ok) { $failed++ }

        $results.Add([pscustomobject]@{
            Target = $t.Name
            Url    = $t.Url
            OK     = $ok
            Ms     = $sw.ElapsedMilliseconds
            Body   = ($resp | ConvertTo-Json -Compress)
        })
    } catch {
        $sw.Stop()
        $failed++
        $results.Add([pscustomobject]@{
            Target = $t.Name
            Url    = $t.Url
            OK     = $false
            Ms     = $sw.ElapsedMilliseconds
            Body   = $_.Exception.Message
        })
    }
}

$results | Format-Table -AutoSize

$reportDir = Join-Path $Root "docs\reports"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$report = Join-Path $reportDir "smoke_api_$stamp.json"
$results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $report -Encoding UTF8
Write-Host "Report: $report"

if ($failed -gt 0) {
    throw "Smoke test failed: $failed endpoint(s)."
} else {
    Write-Host "Smoke test passed."
}
