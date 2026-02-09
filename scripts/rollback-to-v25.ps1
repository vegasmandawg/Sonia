<#
.SYNOPSIS
    Rollback from v2.6-dev to v2.5.0 (v2.5.0-rc1 tag)

.DESCRIPTION
    Safe rollback procedure:
    1. Stop all services (including vision-capture and perception)
    2. Git checkout v2.5.0-rc1 tag
    3. Restart core services
    4. Verify health

    Use -DryRun to validate without executing.

.EXAMPLE
    .\rollback-to-v25.ps1
    .\rollback-to-v25.ps1 -DryRun
#>

param(
    [switch]$DryRun,
    [string]$TargetTag = "v2.5.0-rc1"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "  SONIA v2.6 -> v2.5 Rollback" -ForegroundColor Yellow
Write-Host "  Target: $TargetTag" -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  MODE: DRY RUN (no changes)" -ForegroundColor Cyan
}
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

# Step 1: Verify target tag exists
Write-Host "[1/5] Verifying target tag..." -ForegroundColor Cyan
$tagExists = git tag -l $TargetTag 2>$null
if (-not $tagExists) {
    Write-Host "  ERROR: Tag '$TargetTag' not found" -ForegroundColor Red
    exit 1
}
Write-Host "  Tag '$TargetTag' found" -ForegroundColor Green

# Step 2: Save current state
Write-Host "[2/5] Recording current state..." -ForegroundColor Cyan
$currentBranch = git branch --show-current 2>$null
$currentCommit = git rev-parse --short HEAD 2>$null
Write-Host "  Current: $currentBranch @ $currentCommit"
if ($DryRun) {
    Write-Host "  [DRY RUN] Would save rollback marker" -ForegroundColor Cyan
} else {
    $markerDir = "S:\reports\rollback"
    if (-not (Test-Path $markerDir)) { New-Item -ItemType Directory -Path $markerDir -Force | Out-Null }
    $marker = @{
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        from_branch = $currentBranch
        from_commit = $currentCommit
        to_tag = $TargetTag
    }
    $marker | ConvertTo-Json | Set-Content "$markerDir\rollback-$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
    Write-Host "  Rollback marker saved" -ForegroundColor Green
}

# Step 3: Stop services
Write-Host "[3/5] Stopping all services..." -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  [DRY RUN] Would stop all services" -ForegroundColor Cyan
} else {
    if (Test-Path "S:\stop-sonia-stack.ps1") {
        try {
            & "S:\stop-sonia-stack.ps1"
        } catch {
            Write-Host "  Warning: stop script error: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    # Also kill vision-capture and perception if running
    $v26Ports = @(7060, 7070)
    foreach ($port in $v26Ports) {
        $proc = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($proc) {
            Stop-Process -Id $proc.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "  Stopped process on port $port" -ForegroundColor Yellow
        }
    }
    Write-Host "  Services stopped" -ForegroundColor Green
}

# Step 4: Checkout target
Write-Host "[4/5] Checking out $TargetTag..." -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  [DRY RUN] Would run: git checkout $TargetTag" -ForegroundColor Cyan
} else {
    git stash --include-untracked 2>$null
    git checkout $TargetTag
    Write-Host "  Checked out $TargetTag" -ForegroundColor Green
}

# Step 5: Restart and verify
Write-Host "[5/5] Restarting services..." -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  [DRY RUN] Would restart and verify health" -ForegroundColor Cyan
} else {
    if (Test-Path "S:\start-sonia-stack.ps1") {
        & "S:\start-sonia-stack.ps1"
        Start-Sleep -Seconds 5
        # Health check
        $allOk = $true
        foreach ($port in @(7000, 7010, 7020, 7030, 7040, 7050)) {
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 10
                if ($r.status -eq "ok") {
                    Write-Host "  Port $port : OK" -ForegroundColor Green
                } else {
                    Write-Host "  Port $port : DEGRADED" -ForegroundColor Yellow
                    $allOk = $false
                }
            } catch {
                Write-Host "  Port $port : DOWN" -ForegroundColor Red
                $allOk = $false
            }
        }
        if ($allOk) {
            Write-Host "  All services healthy" -ForegroundColor Green
        } else {
            Write-Host "  Warning: some services not healthy" -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Yellow
if ($DryRun) {
    Write-Host "  DRY RUN COMPLETE -- no changes made" -ForegroundColor Cyan
} else {
    Write-Host "  ROLLBACK COMPLETE to $TargetTag" -ForegroundColor Green
    Write-Host "  To return to v2.6: git checkout v2.6-dev" -ForegroundColor Cyan
}
Write-Host "================================================================" -ForegroundColor Yellow
