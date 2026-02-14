<#
.SYNOPSIS
Legacy wrapper for the canonical top-level Sonia launcher.

.DESCRIPTION
This script is kept for backward compatibility only.
Canonical entrypoint: S:\start-sonia-stack.ps1
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$Root = "S:\",

    [Parameter(Mandatory=$false)]
    [switch]$Reload,

    [Parameter(Mandatory=$false)]
    [switch]$SkipHealthCheck,

    [Parameter(Mandatory=$false)]
    [switch]$SkipPreflight,

    [Parameter(Mandatory=$false)]
    [switch]$TestOnly,

    [Parameter(Mandatory=$false)]
    [switch]$LaunchUI,

    [Parameter(Mandatory=$false)]
    [int]$HealthCheckTimeoutSeconds = 30
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
    -Root $Root `
    -Reload:$Reload `
    -SkipHealthCheck:$SkipHealthCheck `
    -SkipPreflight:$SkipPreflight `
    -TestOnly:$TestOnly `
    -LaunchUI:$LaunchUI `
    -HealthCheckTimeoutSeconds $HealthCheckTimeoutSeconds

exit $LASTEXITCODE
