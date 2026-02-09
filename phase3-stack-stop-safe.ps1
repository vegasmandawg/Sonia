# Safe shutdown script for Phase 3 Gate 1
# ASCII-only version for compatibility

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\"
)

$ErrorActionPreference = "Continue"

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  SONIA STACK SHUTDOWN (Safe ASCII Version)" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$root = $Root

# Kill all Python processes (simplest approach for testing)
Write-Host "Stopping all services..." -ForegroundColor Gray
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        Write-Host "  Terminating process $($_.Id)..." -ForegroundColor Gray
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    } catch {
        # Process already gone, that's fine
    }
}

Start-Sleep -Seconds 1

# Verify all stopped
$remaining = Get-Process python -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Host "  WARNING: Some Python processes still running" -ForegroundColor Yellow
} else {
    Write-Host "  All processes stopped" -ForegroundColor Green
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  SHUTDOWN COMPLETE" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
