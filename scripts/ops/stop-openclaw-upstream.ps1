<#---------------------------------------------------------------------------
stop-openclaw-upstream.ps1
Gracefully stops the OpenClaw upstream gateway service started by
run-openclaw-upstream.ps1

Usage:
  .\stop-openclaw-upstream.ps1           # Graceful (10s timeout)
  .\stop-openclaw-upstream.ps1 -Force    # Force kill immediately
---------------------------------------------------------------------------#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [ValidateNotNullOrEmpty()]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [int]$GracefulTimeoutSeconds = 10,

    [Parameter(Mandatory=$false)]
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Normalize-Root { param([string]$Path) if ($Path -and -not $Path.EndsWith("\")) { return "$Path\" } return $Path }

$Root = Normalize-Root $Root
$PidFile = Join-Path $Root "state\pids\openclaw-upstream.pid"

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "[openclaw] No PID file found. Service is not running."
    exit 0
}

$pidContent = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
if (-not $pidContent -or -not ($pidContent -as [int])) {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "[openclaw] Invalid PID file. Service is not running."
    exit 0
}

$procId = [int]$pidContent

try {
    $proc = Get-Process -Id $procId -ErrorAction Stop
} catch {
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "[openclaw] Process $procId not found. Service is not running."
    exit 0
}

Write-Host "[openclaw] Stopping gateway (PID $procId)..."

if ($Force) {
    Write-Host "[openclaw] Force killing process..."
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
} else {
    Write-Host "[openclaw] Sending SIGTERM (graceful shutdown, ${GracefulTimeoutSeconds}s timeout)..."
    $proc.CloseMainWindow() | Out-Null
    $stopped = $proc.WaitForExit($GracefulTimeoutSeconds * 1000)
    if (-not $stopped) {
        Write-Host "[openclaw] Process did not exit gracefully. Force killing..."
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 200
    }
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "[openclaw] Gateway stopped."
