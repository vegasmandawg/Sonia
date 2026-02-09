$ErrorActionPreference = "Stop"

# Launch with stderr/stdout redirection to catch any startup errors
$proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-ExecutionPolicy Bypass -File `"S:\scripts\testing\soak-monitor.ps1`" -DurationHours 48" `
    -PassThru `
    -RedirectStandardOutput "S:\artifacts\phase3\soak\monitor-stdout.txt" `
    -RedirectStandardError "S:\artifacts\phase3\soak\monitor-stderr.txt" `
    -WindowStyle Hidden

# Wait longer to see if it stays alive
Start-Sleep -Seconds 5
$alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue

@{
    status = if ($alive) { "RUNNING" } else { "DIED" }
    monitor_pid = $proc.Id
    exit_code = if (-not $alive -and $proc.HasExited) { $proc.ExitCode } else { "still running" }
    launch_time = Get-Date -Format "o"
} | ConvertTo-Json | Out-File -FilePath "S:\artifacts\phase3\soak\launch-status.json" -Encoding UTF8
