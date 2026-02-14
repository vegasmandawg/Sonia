<#
.SYNOPSIS
Legacy v2 wrapper for the canonical top-level Sonia launcher.

.DESCRIPTION
This script is kept for backward compatibility only.
Canonical entrypoint: S:\start-sonia-stack.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipHealthCheck,
    [switch]$TestOnly,
    [int]$StartupTimeoutSeconds = 90
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$canonicalLauncher = Join-Path $repoRoot "start-sonia-stack.ps1"

if (-not (Test-Path -LiteralPath $canonicalLauncher)) {
    Write-Host "[FAIL] Canonical launcher not found: $canonicalLauncher" -ForegroundColor Red
    exit 1
}

Write-Host "[WARN] Legacy wrapper in use. Prefer .\start-sonia-stack.ps1 from repo root." -ForegroundColor Yellow

& $canonicalLauncher `
    -SkipHealthCheck:$SkipHealthCheck `
    -TestOnly:$TestOnly `
    -HealthCheckTimeoutSeconds $StartupTimeoutSeconds

exit $LASTEXITCODE
