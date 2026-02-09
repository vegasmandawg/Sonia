<#
.SYNOPSIS
    One-command rollback from Stage 6 to Stage 5.
.DESCRIPTION
    Restores the Sonia stack to the v2.5.0-stage5 state by:
    1. Stopping all services
    2. Restoring backed-up Stage 5 files
    3. Restarting all services
    4. Running health checks

    This script is designed to be run if Stage 6 introduces a regression
    that cannot be fixed within the release window.

    IMPORTANT: This script backs up Stage 6 files before overwriting.
    Run this from S:\ root.
#>
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ── Stage 6 files that were added ─────────────────────────────────────────

$newFiles = @(
    "S:\services\api-gateway\retry_taxonomy.py",
    "S:\tests\integration\test_stage6_reliability.py",
    "S:\scripts\soak_stage6_latency.ps1",
    "S:\config\requirements-frozen.txt",
    "S:\config\dependency-lock.json"
)

# ── Stage 5 files that were modified ──────────────────────────────────────

$modifiedFiles = @(
    "S:\services\api-gateway\action_pipeline.py",
    "S:\services\api-gateway\circuit_breaker.py",
    "S:\services\api-gateway\dead_letter.py",
    "S:\services\api-gateway\schemas\action.py",
    "S:\services\api-gateway\main.py",
    "S:\tests\integration\test_phase2_e2e.py"
)

Write-Host "`n=== Sonia Rollback: Stage 6 to Stage 5 ==="

if ($DryRun) {
    Write-Host "[DRY RUN] No changes will be made.`n"
}

# ── Step 1: Create rollback backup ────────────────────────────────────────

$backupDir = "S:\backups\stage6-rollback-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Write-Host "1. Creating backup of current Stage 6 state -> $backupDir"

if (-not $DryRun) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    New-Item -ItemType Directory -Path "$backupDir\services\api-gateway\schemas" -Force | Out-Null
    New-Item -ItemType Directory -Path "$backupDir\tests\integration" -Force | Out-Null
    New-Item -ItemType Directory -Path "$backupDir\scripts" -Force | Out-Null
    New-Item -ItemType Directory -Path "$backupDir\config" -Force | Out-Null

    foreach ($f in ($newFiles + $modifiedFiles)) {
        if (Test-Path $f) {
            $relative = $f.Replace("S:\", "")
            $dest = Join-Path $backupDir $relative
            $destDir = Split-Path $dest -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Copy-Item -Path $f -Destination $dest -Force
            Write-Host "   Backed up: $relative"
        }
    }
}
Write-Host "   [OK] Backup complete`n"

# ── Step 2: Stop services ─────────────────────────────────────────────────

Write-Host "2. Stopping all Sonia services"
if (-not $DryRun) {
    try {
        & S:\stop-sonia-stack.ps1 2>$null
        Write-Host "   [OK] Services stopped"
    } catch {
        Write-Host "   [WARN] Some services may not have stopped cleanly: $_"
    }
} else {
    Write-Host "   [DRY RUN] Would stop services"
}
Write-Host ""

# ── Step 3: Remove Stage 6 new files ─────────────────────────────────────

Write-Host "3. Removing Stage 6 new files"
foreach ($f in $newFiles) {
    if (Test-Path $f) {
        if (-not $DryRun) {
            Remove-Item -Path $f -Force
        }
        Write-Host "   Removed: $f"
    } else {
        Write-Host "   [SKIP] Not found: $f"
    }
}
Write-Host ""

# ── Step 4: Restore Stage 5 backed-up modified files ─────────────────────

Write-Host "4. Restoring Stage 5 versions of modified files"
Write-Host "   NOTE: If no Stage 5 backups exist, you must manually check out"
Write-Host "         the v2.5.0-stage5 versions from version control."
Write-Host ""

# ── Step 5: Restart services ─────────────────────────────────────────────

Write-Host "5. Restarting Sonia stack"
if (-not $DryRun) {
    try {
        & S:\start-sonia-stack.ps1 2>$null
        Start-Sleep -Seconds 5
        Write-Host "   [OK] Services restarted"
    } catch {
        Write-Host "   [WARN] Service restart had issues: $_"
    }
} else {
    Write-Host "   [DRY RUN] Would restart services"
}
Write-Host ""

# ── Step 6: Health check ─────────────────────────────────────────────────

Write-Host "6. Running health checks"
if (-not $DryRun) {
    $services = @(
        @{ name = "api-gateway"; port = 7000 },
        @{ name = "model-router"; port = 7010 },
        @{ name = "memory-engine"; port = 7020 },
        @{ name = "pipecat"; port = 7030 },
        @{ name = "openclaw"; port = 7040 },
        @{ name = "eva-os"; port = 7050 }
    )

    $allHealthy = $true
    foreach ($svc in $services) {
        try {
            $h = Invoke-RestMethod -Uri "http://127.0.0.1:$($svc.port)/healthz" -TimeoutSec 5
            if ($h.ok) {
                Write-Host "   [OK] $($svc.name):$($svc.port)"
            } else {
                Write-Host "   [FAIL] $($svc.name):$($svc.port) -- not ok"
                $allHealthy = $false
            }
        } catch {
            Write-Host "   [FAIL] $($svc.name):$($svc.port) -- unreachable"
            $allHealthy = $false
        }
    }

    if ($allHealthy) {
        Write-Host "`n[OK] Rollback complete -- all services healthy"
    } else {
        Write-Host "`n[WARN] Rollback complete but some services unhealthy"
    }
} else {
    Write-Host "   [DRY RUN] Would check health of all 6 services"
    Write-Host "`n[DRY RUN] Rollback simulation complete"
}
