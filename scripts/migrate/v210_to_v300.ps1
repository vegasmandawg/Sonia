<#
.SYNOPSIS
    Migrate SONIA from v2.10.x to v3.0.0 (M1: Contract + Config Cut)

.DESCRIPTION
    - Backs up S:\data\ and S:\config\ to timestamped archive
    - Transforms sonia-config.json (adds config_schema, updates version, adds endpoint arrays)
    - Validates result via Python config_validator
    - Supports -DryRun for preview without changes

.PARAMETER DryRun
    Preview changes without writing to disk.

.PARAMETER BackupDir
    Override backup destination (default: S:\backups\migrate-v300-<timestamp>)

.EXAMPLE
    .\v210_to_v300.ps1
    .\v210_to_v300.ps1 -DryRun
#>
param(
    [switch]$DryRun,
    [string]$BackupDir = ""
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$root = "S:\"
$configPath = Join-Path $root "config\sonia-config.json"
$python = "S:\envs\sonia-core\python.exe"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " SONIA v2.10 -> v3.0.0 Migration (M1)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] No changes will be written." -ForegroundColor Yellow
    Write-Host ""
}

# ── Step 1: Validate source ─────────────────────────────────────────────
Write-Host "[1/5] Validating source config..." -ForegroundColor White

if (-not (Test-Path $configPath)) {
    Write-Host "FAIL: Config not found at $configPath" -ForegroundColor Red
    exit 1
}

$rawJson = Get-Content $configPath -Raw -Encoding UTF8
$config = $rawJson | ConvertFrom-Json

$currentVersion = $config.sonia_version
Write-Host "  Current version: $currentVersion"

if ($currentVersion -eq "3.0.0") {
    Write-Host "  Already at v3.0.0 -- nothing to do." -ForegroundColor Green
    exit 0
}

if ($currentVersion -notmatch "^2\.10") {
    Write-Host "  WARNING: Expected v2.10.x, got $currentVersion" -ForegroundColor Yellow
}

# ── Step 2: Backup ──────────────────────────────────────────────────────
Write-Host "[2/5] Creating backup..." -ForegroundColor White

if (-not $BackupDir) {
    $BackupDir = Join-Path $root "backups\migrate-v300-$timestamp"
}

if (-not $DryRun) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

    # Backup config directory
    $configBackup = Join-Path $BackupDir "config"
    Copy-Item -Path (Join-Path $root "config") -Destination $configBackup -Recurse -Force

    # Backup data directory (if exists)
    $dataDir = Join-Path $root "data"
    if (Test-Path $dataDir) {
        $dataBackup = Join-Path $BackupDir "data"
        Copy-Item -Path $dataDir -Destination $dataBackup -Recurse -Force
    }

    Write-Host "  Backup created at: $BackupDir" -ForegroundColor Green
} else {
    Write-Host "  [DRY RUN] Would backup to: $BackupDir" -ForegroundColor Yellow
}

# ── Step 3: Transform config ────────────────────────────────────────────
Write-Host "[3/5] Transforming config..." -ForegroundColor White

# Add config_schema if missing
if (-not $config.config_schema) {
    $config | Add-Member -NotePropertyName "config_schema" -NotePropertyValue "3.0.0" -Force
    Write-Host "  + Added config_schema: 3.0.0"
}

# Update sonia_version
$config.sonia_version = "3.0.0"
Write-Host "  + Updated sonia_version: 3.0.0"

# Update session_id
$config.session_id = "sonia-v3-productization-2026-02"
Write-Host "  + Updated session_id"

# Remove final_iteration if present
if ($config.PSObject.Properties["final_iteration"]) {
    $config.PSObject.Properties.Remove("final_iteration")
    Write-Host "  - Removed final_iteration"
}

# Add api_gateway endpoint arrays if missing
$gw = $config.api_gateway
if ($gw) {
    if (-not $gw.internal_endpoints) {
        $gw | Add-Member -NotePropertyName "internal_endpoints" -NotePropertyValue @("healthz", "status", "deps") -Force
        Write-Host "  + Added api_gateway.internal_endpoints"
    }
    if (-not $gw.public_endpoints) {
        $gw | Add-Member -NotePropertyName "public_endpoints" -NotePropertyValue @(
            "turn", "chat", "sessions", "stream", "actions", "confirmations",
            "diagnostics", "backups", "capabilities", "ui/stream"
        ) -Force
        Write-Host "  + Added api_gateway.public_endpoints"
    }
}

# ── Step 4: Write transformed config ────────────────────────────────────
Write-Host "[4/5] Writing transformed config..." -ForegroundColor White

$newJson = $config | ConvertTo-Json -Depth 10

if (-not $DryRun) {
    $newJson | Set-Content $configPath -Encoding UTF8 -Force
    Write-Host "  Config written to $configPath" -ForegroundColor Green
} else {
    Write-Host "  [DRY RUN] Would write to $configPath" -ForegroundColor Yellow
}

# ── Step 5: Validate via Python schema ──────────────────────────────────
Write-Host "[5/5] Validating against schema..." -ForegroundColor White

if (-not $DryRun) {
    $validateScript = @"
import sys
sys.path.insert(0, r'S:\services\shared')
from config_validator import SoniaConfig, ConfigValidationError
try:
    cfg = SoniaConfig()
    print(f'OK: version={cfg.version}, schema={cfg.schema_version}')
    sys.exit(0)
except ConfigValidationError as e:
    print(f'FAIL: {e}')
    sys.exit(1)
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
"@
    $result = & $python -c $validateScript 2>&1
    Write-Host "  $result"

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Schema validation FAILED -- restoring backup..." -ForegroundColor Red
        $backupConfig = Join-Path $BackupDir "config\sonia-config.json"
        Copy-Item -Path $backupConfig -Destination $configPath -Force
        Write-Host "  Config restored from backup." -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "  [DRY RUN] Would validate schema" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Migration complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Backup: $BackupDir"
Write-Host "  Version: 2.10.x -> 3.0.0"
Write-Host "  Config schema: 3.0.0"
Write-Host ""
