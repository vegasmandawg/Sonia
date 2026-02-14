<#
.SYNOPSIS
    Prunes empty (0-byte) session files from S:\data\sessions.

.DESCRIPTION
    Scans S:\data\sessions recursively for 0-byte files and removes them.
    Logs the count of removed files. Safe to run as a scheduled task.

.EXAMPLE
    .\prune-empty-sessions.ps1
    .\prune-empty-sessions.ps1 -DryRun
#>
param(
    [string]$SessionDir = "S:\data\sessions",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

Write-Host "[$timestamp] Session prune starting -- target: $SessionDir"

# Ensure directory exists
if (-not (Test-Path $SessionDir)) {
    New-Item -Path $SessionDir -ItemType Directory -Force | Out-Null
    Write-Host "[$timestamp] Created session directory: $SessionDir"
    Write-Host "[$timestamp] No files to prune (fresh directory)"
    exit 0
}

# Find empty files
$emptyFiles = Get-ChildItem -Path $SessionDir -File -Recurse | Where-Object { $_.Length -eq 0 }
$count = 0
if ($emptyFiles) {
    $count = @($emptyFiles).Count
}

if ($count -eq 0) {
    Write-Host "[$timestamp] No empty session files found -- clean"
    exit 0
}

Write-Host "[$timestamp] Found $count empty session file(s)"

if ($DryRun) {
    Write-Host "[$timestamp] DRY RUN -- would remove:"
    foreach ($f in $emptyFiles) {
        Write-Host "  $($f.FullName)"
    }
} else {
    foreach ($f in $emptyFiles) {
        Remove-Item -Path $f.FullName -Force
        Write-Host "  Removed: $($f.FullName)"
    }
    Write-Host "[$timestamp] Pruned $count empty session file(s)"
}

# Log to prune history
$logDir = "S:\logs\services"
if (Test-Path $logDir) {
    $logLine = "$timestamp | pruned=$count | dry_run=$($DryRun.IsPresent)"
    Add-Content -Path (Join-Path $logDir "session-prune.log") -Value $logLine
}

exit 0
