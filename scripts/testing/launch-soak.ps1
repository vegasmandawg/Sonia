$ErrorActionPreference = "Stop"

# Launch soak-monitor as a detached background process
$pinfo = New-Object System.Diagnostics.ProcessStartInfo
$pinfo.FileName = "powershell.exe"
$pinfo.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"S:\scripts\testing\soak-monitor.ps1`" -DurationHours 48"
$pinfo.UseShellExecute = $true
$pinfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden

$proc = [System.Diagnostics.Process]::Start($pinfo)

@{
    status = "LAUNCHED"
    monitor_pid = $proc.Id
    launch_time = Get-Date -Format "o"
    duration_hours = 48
    expected_end = (Get-Date).AddHours(48).ToString("o")
    log_file = "S:\artifacts\phase3\soak\soak-monitor.log"
    snapshots_dir = "S:\artifacts\phase3\soak\snapshots"
    checkpoints_dir = "S:\artifacts\phase3\soak\checkpoints"
} | ConvertTo-Json | Out-File -FilePath "S:\artifacts\phase3\soak\launch-status.json" -Encoding UTF8

"Soak monitor launched as PID $($proc.Id)" | Out-File -FilePath "S:\artifacts\phase3\soak\launch-log.txt" -Encoding UTF8
