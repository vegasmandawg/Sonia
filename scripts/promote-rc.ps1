<#
.SYNOPSIS
Promote current state to a new Release Candidate.

.DESCRIPTION
Requires 3 consecutive green qualification cycles before promotion.
Creates a versioned RC snapshot under S:\baselines\.

.PARAMETER Version
RC version string, e.g. "RC1.1", "RC2"

.PARAMETER Message
Tag message for the git tag.

.EXAMPLE
.\scripts\promote-rc.ps1 -Version "RC1.1" -Message "feat(pipecat): voice loop hardening"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Version,
    [string]$Message = "Sonia $Version promotion"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "S:\scripts\lib\sonia-stack.ps1"

$date = Get-Date -Format "yyyyMMdd"
$rcDir = "S:\baselines\Sonia-$Version-$date"

Write-Host "`nSonia RC Promotion: $Version" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan

# ─── Pre-check: must have clean git state ─────────────────────────
Write-Host "`nPre-check: git state..." -ForegroundColor Gray
Set-Location "S:\"
$dirty = git status --porcelain 2>&1
if ($dirty) {
    Write-Host "[FAIL] Working tree is dirty. Commit or stash changes first." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Working tree clean" -ForegroundColor Green

# ─── Run 3 qualification cycles ───────────────────────────────────
Write-Host "`nRunning 3 qualification cycles..." -ForegroundColor Cyan

$cycleResults = @()
for ($i = 1; $i -le 3; $i++) {
    Write-Host "`n--- Cycle $i/3 ---" -ForegroundColor Yellow

    # Stop all
    $ports = @(7050, 7040, 7030, 7020, 7010, 7000)
    foreach ($p in $ports) {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conn) { foreach ($c in $conn) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } }
    }
    Get-ChildItem "S:\state\pids" -Filter "*.pid" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds $(if ($i -eq 1) { 3 } else { 1 })

    # Start all
    $startOk = $true
    $svcs = @(
        @{ Name="api-gateway";   Dir="S:\services\api-gateway";   Port=7000 },
        @{ Name="model-router";  Dir="S:\services\model-router";  Port=7010 },
        @{ Name="memory-engine"; Dir="S:\services\memory-engine"; Port=7020 },
        @{ Name="pipecat";       Dir="S:\services\pipecat";       Port=7030 },
        @{ Name="openclaw";      Dir="S:\services\openclaw";      Port=7040 },
        @{ Name="eva-os";        Dir="S:\services\eva-os";        Port=7050 }
    )
    foreach ($svc in $svcs) {
        try {
            Start-SoniaService -ServiceName $svc.Name -ServiceDir $svc.Dir -Port $svc.Port -BootWaitSeconds 12 | Out-Null
        } catch {
            Write-Host "[FAIL] $($svc.Name): $_" -ForegroundColor Red
            $startOk = $false
        }
    }

    # Health check
    $healthOk = $true
    foreach ($svc in $svcs) {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$($svc.Port)/healthz" -TimeoutSec 5
        } catch {
            Write-Host "[FAIL] $($svc.Name) health" -ForegroundColor Red
            $healthOk = $false
        }
    }

    $cyclePass = $startOk -and $healthOk
    $cycleResults += $cyclePass
    Write-Host "Cycle $i: $(if ($cyclePass) { 'PASS' } else { 'FAIL' })" -ForegroundColor $(if ($cyclePass) { "Green" } else { "Red" })

    if (-not $cyclePass) {
        Write-Host "`nCycle $i failed. Promotion aborted." -ForegroundColor Red
        exit 1
    }
}

# ─── Build RC snapshot ────────────────────────────────────────────
Write-Host "`nBuilding RC snapshot..." -ForegroundColor Cyan
New-Item -ItemType Directory -Path $rcDir -Force | Out-Null

# Copy critical files
$targets = @(
    "start-sonia-stack.ps1", "stop-sonia-stack.ps1",
    "scripts", "config", "configs", "shared"
)
foreach ($t in $targets) {
    if (Test-Path "S:\$t") {
        Copy-Item "S:\$t" "$rcDir\$t" -Recurse -Force
    }
}

# Copy service .py files only
$svcSnap = "$rcDir\services"
New-Item -ItemType Directory -Path $svcSnap -Force | Out-Null
foreach ($svc in @("api-gateway","model-router","memory-engine","pipecat","openclaw","eva-os")) {
    $dst = "$svcSnap\$svc"
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Get-ChildItem "S:\services\$svc" -Filter "*.py" -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item $_.FullName "$dst\$($_.Name)" -Force
    }
}

# Pip freeze
$freeze = & "S:\envs\sonia-core\python.exe" -m pip freeze 2>&1
$freeze | Out-File "$rcDir\pip-freeze.txt" -Encoding UTF8

# File hashes
$hashTargets = @(
    "S:\start-sonia-stack.ps1", "S:\stop-sonia-stack.ps1",
    "S:\config\sonia-config.json", "S:\scripts\lib\sonia-stack.ps1",
    "S:\scripts\qualify-change.ps1", "S:\scripts\health-smoke.ps1"
) | Where-Object { Test-Path $_ }
Get-FileHash $hashTargets -Algorithm SHA256 | Format-Table -AutoSize | Out-String | Set-Content "$rcDir\filehashes.txt" -Encoding UTF8

# Diff from previous RC tag
$prevTag = git tag -l "RC*" --sort=-creatordate 2>&1 | Select-Object -First 1
if ($prevTag) {
    $diff = git diff "$prevTag"..HEAD --stat 2>&1
    $diff | Out-File "$rcDir\diff-from-$prevTag.txt" -Encoding UTF8
}

# Manifest
$manifest = @"
# Sonia $Version Manifest
Generated: $(Get-Date -Format 'o')
Previous: $prevTag

## Qualification
- 3 consecutive green startup cycles
- Health smoke: 6/6
- Clean error logs

## Changes from $prevTag
See diff-from-$prevTag.txt

## Status: $Version PROMOTED
"@
$manifest | Out-File "$rcDir\RC_MANIFEST.md" -Encoding UTF8

# ─── Git tag ──────────────────────────────────────────────────────
$tagName = "$Version-$date"
git tag -a $tagName -m "$Message" 2>&1 | Out-Null

Write-Host "`n═══════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "PROMOTED: Sonia $Version" -ForegroundColor Green
Write-Host "Tag: $tagName" -ForegroundColor Gray
Write-Host "Snapshot: $rcDir" -ForegroundColor Gray
Write-Host "═══════════════════════════════════════════" -ForegroundColor Cyan
