$out = @()
$out += "=== SOAK MONITOR STATUS CHECK v2 ==="
$out += "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# Check the actual launched PID from status file
$status = Get-Content "S:\artifacts\phase3\soak\launch-status.json" -Raw | ConvertFrom-Json
$monPID = $status.monitor_pid
$out += "Expected monitor PID: $monPID"

$proc = Get-Process -Id $monPID -ErrorAction SilentlyContinue
if ($proc) {
    $out += "Monitor PID $monPID RUNNING (CPU=$($proc.CPU)s RSS=$([math]::Round($proc.WorkingSet64/1024))KB)"
} else {
    $out += "Monitor PID $monPID NOT RUNNING"
    # Search for any powershell running soak-monitor
    $candidates = Get-Process powershell -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $PID }
    $out += "Other powershell processes: $($candidates.Count)"
    foreach ($c in $candidates) {
        $out += "  PID=$($c.Id) CPU=$($c.CPU)s RSS=$([math]::Round($c.WorkingSet64/1024))KB"
    }
}

# Check log
$logFile = "S:\artifacts\phase3\soak\soak-monitor.log"
if (Test-Path $logFile) {
    $lines = @(Get-Content $logFile)
    $out += "Log file: $($lines.Count) lines"
    $out += "Last 3:"
    $lines | Select-Object -Last 3 | ForEach-Object { $out += "  $_" }
} else {
    $out += "Log: MISSING"
}

# Check snapshots
$snapDir = "S:\artifacts\phase3\soak\snapshots"
$snaps = @(Get-ChildItem $snapDir -Filter "snapshot-*.json" -ErrorAction SilentlyContinue)
$out += "Snapshots: $($snaps.Count)"

# T0 baseline time
$baseline = Get-Content "S:\artifacts\phase3\soak\t0-baseline.json" -Raw | ConvertFrom-Json
$t0 = [datetime]$baseline.start_time
$elapsed = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
$out += "Elapsed since T0: ${elapsed} minutes"
$out += "Next snapshot expected at: $($t0.AddMinutes(15).ToString('HH:mm:ss')) (T0+15m)"

$out | Out-File -FilePath "S:\artifacts\phase3\soak\status-check.txt" -Encoding UTF8
