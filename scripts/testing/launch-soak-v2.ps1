$ErrorActionPreference = "Stop"

# Launch soak-monitor as a detached process using Start-Process
$proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"S:\scripts\testing\soak-monitor.ps1`" -DurationHours 48" `
    -WindowStyle Hidden `
    -PassThru

# Verify it started
Start-Sleep -Seconds 3
$alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue

@{
    status = if ($alive) { "RUNNING" } else { "FAILED_TO_START" }
    monitor_pid = $proc.Id
    launch_time = Get-Date -Format "o"
    duration_hours = 48
    expected_end = (Get-Date).AddHours(48).ToString("yyyy-MM-dd HH:mm:ss")
    log_file = "S:\artifacts\phase3\soak\soak-monitor.log"
    snapshots_dir = "S:\artifacts\phase3\soak\snapshots"
    checkpoints_dir = "S:\artifacts\phase3\soak\checkpoints"
    alive_after_3s = [bool]$alive
} | ConvertTo-Json | Out-File -FilePath "S:\artifacts\phase3\soak\launch-status.json" -Encoding UTF8
