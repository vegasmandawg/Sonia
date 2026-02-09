$out = @()
$out += "=== SOAK MONITOR STATUS CHECK ==="
$out += "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# Check if PID 20232 is alive
$proc = Get-Process -Id 20232 -ErrorAction SilentlyContinue
if ($proc) {
    $out += "Monitor PID 20232: RUNNING (CPU=$($proc.CPU)s RSS=$([math]::Round($proc.WorkingSet64/1024))KB)"
} else {
    $out += "Monitor PID 20232: NOT RUNNING"
}

# Check log file
$logFile = "S:\artifacts\phase3\soak\soak-monitor.log"
if (Test-Path $logFile) {
    $lines = @(Get-Content $logFile)
    $out += "Log file: $($lines.Count) lines"
    $out += "Last 5 lines:"
    $lines | Select-Object -Last 5 | ForEach-Object { $out += "  $_" }
} else {
    $out += "Log file: DOES NOT EXIST"
}

# Check snapshots
$snapDir = "S:\artifacts\phase3\soak\snapshots"
if (Test-Path $snapDir) {
    $snaps = @(Get-ChildItem $snapDir -Filter "snapshot-*.json")
    $out += "Snapshots: $($snaps.Count)"
    if ($snaps.Count -gt 0) {
        $latest = $snaps | Sort-Object Name | Select-Object -Last 1
        $out += "Latest: $($latest.Name)"
    }
} else {
    $out += "Snapshots dir: DOES NOT EXIST"
}

$out | Out-File -FilePath "S:\artifacts\phase3\soak\status-check.txt" -Encoding UTF8
