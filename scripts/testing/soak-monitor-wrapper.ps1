try {
    & "S:\scripts\testing\soak-monitor.ps1" -DurationHours 48 2>&1 | Out-File -FilePath "S:\artifacts\phase3\soak\monitor-output.txt" -Encoding UTF8
} catch {
    "ERROR: $_" | Out-File -FilePath "S:\artifacts\phase3\soak\monitor-error.txt" -Encoding UTF8
}
