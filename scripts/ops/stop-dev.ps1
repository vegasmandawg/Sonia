[CmdletBinding()]
param(
    [string]$Root = "S:\"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $Root.EndsWith("\")) { $Root = "$Root\" }

$pidDir = Join-Path $Root "state\pids"
if (-not (Test-Path $pidDir)) {
    Write-Host "No PID directory found: $pidDir"
    exit 0
}

$pidFiles = Get-ChildItem -Path $pidDir -Filter *.pid -File -ErrorAction SilentlyContinue
if (-not $pidFiles) {
    Write-Host "No running service PID files found."
    exit 0
}

foreach ($f in $pidFiles) {
    $name = [IO.Path]::GetFileNameWithoutExtension($f.Name)
    $pidText = Get-Content -LiteralPath $f.FullName -ErrorAction SilentlyContinue
    if (-not $pidText) {
        Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
        continue
    }

    try {
        $procId = [int]$pidText
        Stop-Process -Id $procId -Force -ErrorAction Stop
        Write-Host "Stopped $name (PID $procId)"
    } catch {
        Write-Host "Stale PID for $name ($pidText)"
    }

    Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
}

Write-Host "All stop operations complete."
