#Requires -Version 5.1
<#
.SYNOPSIS
    Collects audit evidence artifacts into a timestamped binder.

.DESCRIPTION
    Creates a comprehensive audit evidence binder containing:
    - Gate report from latest or specified release
    - Security scan output (bandit static analysis)
    - Backup drill verification
    - Restore capability check
    - Log redaction verification
    - Configuration fingerprints (SHA-256)
    - Documentation version stamps

    Produces a manifest with overall PASS/WARN status.

.PARAMETER Release
    Optional release version to collect gate report from (e.g., "v3.0.0").
    If not specified, uses the latest release in S:\releases\.

.EXAMPLE
    .\collect-audit-evidence.ps1
    Collects evidence for latest release.

.EXAMPLE
    .\collect-audit-evidence.ps1 -Release "v3.0.0"
    Collects evidence for specific release.

.NOTES
    PowerShell 5.1 compatible (ASCII only, no Unicode)
    Requires SONIA stack running for memory engine checks
    Python env: S:\envs\sonia-core\python.exe
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$Release
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Constants ---
$ROOT = "S:\"
$PYTHON_EXE = "S:\envs\sonia-core\python.exe"
$AUDIT_DIR = Join-Path $ROOT "reports\audit"
$RELEASES_DIR = Join-Path $ROOT "releases"
$TIMESTAMP = Get-Date -Format "yyyyMMdd-HHmmss"
$BINDER_DIR = Join-Path $AUDIT_DIR "binder-$TIMESTAMP"

# --- Helper Functions ---

function Write-Evidence {
    param([string]$Message)
    Write-Host "[AUDIT] $Message" -ForegroundColor Cyan
}

function Write-EvidenceWarn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Compute-SHA256 {
    param([string]$Path)
    if (Test-Path $Path) {
        return (Get-FileHash -Path $Path -Algorithm SHA256).Hash
    }
    return $null
}

function Collect-GateReport {
    param([string]$TargetRelease)

    Write-Evidence "Collecting gate report..."

    if ($TargetRelease) {
        $releaseDir = Join-Path $RELEASES_DIR $TargetRelease
        if (-not (Test-Path $releaseDir)) {
            Write-EvidenceWarn "Release directory not found: $releaseDir"
            return $false
        }
    } else {
        # Find latest release
        $releases = Get-ChildItem -Path $RELEASES_DIR -Directory -ErrorAction SilentlyContinue |
                    Sort-Object Name -Descending
        if (-not $releases) {
            Write-EvidenceWarn "No release directories found in $RELEASES_DIR"
            return $false
        }
        $releaseDir = $releases[0].FullName
        Write-Evidence "Using latest release: $($releases[0].Name)"
    }

    # Look for gate report
    $gateReport = Get-ChildItem -Path $releaseDir -Filter "*gate*.json" -ErrorAction SilentlyContinue |
                  Select-Object -First 1

    if (-not $gateReport) {
        Write-EvidenceWarn "No gate report found in $releaseDir"
        return $false
    }

    Copy-Item -Path $gateReport.FullName -Destination (Join-Path $BINDER_DIR "gate-report.json")
    Write-Evidence "Collected: gate-report.json"
    return $true
}

function Collect-SecurityScan {
    Write-Evidence "Running security scan..."

    $scanScript = Join-Path $ROOT "scripts\security-scan.ps1"
    if (-not (Test-Path $scanScript)) {
        Write-EvidenceWarn "Security scan script not found: $scanScript"
        "SKIP: security-scan.ps1 not available" | Out-File -FilePath (Join-Path $BINDER_DIR "security-scan.txt") -Encoding ASCII
        return $false
    }

    try {
        $output = & powershell.exe -ExecutionPolicy Bypass -File $scanScript 2>&1 | Out-String
        $output | Out-File -FilePath (Join-Path $BINDER_DIR "security-scan.txt") -Encoding ASCII
        Write-Evidence "Collected: security-scan.txt"
        return $true
    } catch {
        Write-EvidenceWarn "Security scan failed: $_"
        "ERROR: $($_.Exception.Message)" | Out-File -FilePath (Join-Path $BINDER_DIR "security-scan.txt") -Encoding ASCII
        return $false
    }
}

function Collect-BackupDrill {
    Write-Evidence "Running backup drill..."

    $backupDir = Join-Path $ROOT "state\backups"
    if (-not (Test-Path $backupDir)) {
        Write-EvidenceWarn "Backup directory not found: $backupDir"
        "SKIP: No backups directory" | Out-File -FilePath (Join-Path $BINDER_DIR "backup-drill.txt") -Encoding ASCII
        return $false
    }

    # Find latest backup
    $backups = Get-ChildItem -Path $backupDir -Filter "backup-*.json" -ErrorAction SilentlyContinue |
               Sort-Object Name -Descending

    if (-not $backups) {
        Write-EvidenceWarn "No backups found in $backupDir"
        "SKIP: No backup files found" | Out-File -FilePath (Join-Path $BINDER_DIR "backup-drill.txt") -Encoding ASCII
        return $false
    }

    $latestBackup = $backups[0].FullName
    Write-Evidence "Verifying backup: $($backups[0].Name)"

    try {
        $manifest = Get-Content -Path $latestBackup -Raw | ConvertFrom-Json
        $dbPath = $manifest.db_path

        if (-not (Test-Path $dbPath)) {
            Write-EvidenceWarn "Database file not found: $dbPath"
            "ERROR: Database file missing" | Out-File -FilePath (Join-Path $BINDER_DIR "backup-drill.txt") -Encoding ASCII
            return $false
        }

        # Verify DB integrity using sqlite3
        $integrityCmd = "& `"$PYTHON_EXE`" -c `"import sqlite3; conn = sqlite3.connect('$($dbPath -replace '\\', '/')'); print(conn.execute('PRAGMA integrity_check').fetchone()[0])`""
        $result = Invoke-Expression $integrityCmd 2>&1 | Out-String

        $output = @"
Backup: $($backups[0].Name)
Database: $dbPath
Manifest SHA-256: $($manifest.manifest_hash)
Integrity Check: $result
Status: $(if ($result -match 'ok') { 'PASS' } else { 'FAIL' })
"@

        $output | Out-File -FilePath (Join-Path $BINDER_DIR "backup-drill.txt") -Encoding ASCII
        Write-Evidence "Collected: backup-drill.txt"
        return ($result -match 'ok')
    } catch {
        Write-EvidenceWarn "Backup verification failed: $_"
        "ERROR: $($_.Exception.Message)" | Out-File -FilePath (Join-Path $BINDER_DIR "backup-drill.txt") -Encoding ASCII
        return $false
    }
}

function Collect-RestoreVerification {
    Write-Evidence "Verifying restore capability..."

    try {
        # Call memory engine /pragmas endpoint
        $response = Invoke-RestMethod -Uri "http://localhost:7020/pragmas" -Method Get -TimeoutSec 10

        $output = @"
Memory Engine Pragmas Check
Endpoint: http://localhost:7020/pragmas
Integrity Check: $($response.integrity_check)
Foreign Keys: $($response.foreign_keys)
Status: $(if ($response.integrity_check -eq 'ok' -and $response.foreign_keys -eq 'ok') { 'PASS' } else { 'FAIL' })
"@

        $output | Out-File -FilePath (Join-Path $BINDER_DIR "restore-verify.txt") -Encoding ASCII
        Write-Evidence "Collected: restore-verify.txt"
        return ($response.integrity_check -eq 'ok' -and $response.foreign_keys -eq 'ok')
    } catch {
        Write-EvidenceWarn "Restore verification failed: $_"
        "ERROR: Memory engine not responding or check failed: $($_.Exception.Message)" | Out-File -FilePath (Join-Path $BINDER_DIR "restore-verify.txt") -Encoding ASCII
        return $false
    }
}

function Collect-RedactionVerification {
    Write-Evidence "Running redaction verification..."

    $testFile = Join-Path $ROOT "tests\integration\test_log_redaction_verification.py"
    if (-not (Test-Path $testFile)) {
        Write-EvidenceWarn "Redaction test file not found: $testFile"
        "SKIP: test_log_redaction_verification.py not found" | Out-File -FilePath (Join-Path $BINDER_DIR "redaction-verify.txt") -Encoding ASCII
        return $false
    }

    try {
        Push-Location $ROOT
        $output = & $PYTHON_EXE -m pytest "$testFile" -v 2>&1 | Out-String
        Pop-Location

        $output | Out-File -FilePath (Join-Path $BINDER_DIR "redaction-verify.txt") -Encoding ASCII
        Write-Evidence "Collected: redaction-verify.txt"
        return ($output -match "passed" -and $output -notmatch "failed")
    } catch {
        Pop-Location
        Write-EvidenceWarn "Redaction verification failed: $_"
        "ERROR: $($_.Exception.Message)" | Out-File -FilePath (Join-Path $BINDER_DIR "redaction-verify.txt") -Encoding ASCII
        return $false
    }
}

function Collect-ConfigFingerprint {
    Write-Evidence "Computing configuration fingerprint..."

    $configFiles = @(
        @{Path = "config\sonia-config.json"; Name = "sonia-config.json"}
        @{Path = "requirements-frozen.txt"; Name = "requirements-frozen.txt"}
        @{Path = "dependency-lock.json"; Name = "dependency-lock.json"}
    )

    $fingerprints = @()
    foreach ($file in $configFiles) {
        $fullPath = Join-Path $ROOT $file.Path
        if (Test-Path $fullPath) {
            $hash = Compute-SHA256 -Path $fullPath
            $fingerprints += @{
                file = $file.Name
                path = $file.Path
                sha256 = $hash
                exists = $true
            }
        } else {
            $fingerprints += @{
                file = $file.Name
                path = $file.Path
                sha256 = $null
                exists = $false
            }
            Write-EvidenceWarn "Config file not found: $fullPath"
        }
    }

    $fingerprint = @{
        timestamp = (Get-Date -Format "o")
        files = $fingerprints
    }

    $fingerprint | ConvertTo-Json -Depth 10 | Out-File -FilePath (Join-Path $BINDER_DIR "config-fingerprint.json") -Encoding ASCII
    Write-Evidence "Collected: config-fingerprint.json"
    return ($fingerprints | Where-Object { -not $_.exists }).Count -eq 0
}

function Collect-DocStamps {
    Write-Evidence "Collecting documentation stamps..."

    $docsDir = Join-Path $ROOT "docs"
    if (-not (Test-Path $docsDir)) {
        Write-EvidenceWarn "Docs directory not found: $docsDir"
        @{error = "docs directory not found"} | ConvertTo-Json | Out-File -FilePath (Join-Path $BINDER_DIR "doc-stamps.json") -Encoding ASCII
        return $false
    }

    $docFiles = Get-ChildItem -Path $docsDir -Filter "*.md" -File
    $stamps = @()

    foreach ($doc in $docFiles) {
        $stamps += @{
            file = $doc.Name
            last_modified = $doc.LastWriteTime.ToString("o")
            size_bytes = $doc.Length
        }
    }

    $stampData = @{
        timestamp = (Get-Date -Format "o")
        docs_directory = $docsDir
        document_count = $stamps.Count
        documents = $stamps
    }

    $stampData | ConvertTo-Json -Depth 10 | Out-File -FilePath (Join-Path $BINDER_DIR "doc-stamps.json") -Encoding ASCII
    Write-Evidence "Collected: doc-stamps.json ($($stamps.Count) documents)"
    return $true
}

function Write-BinderManifest {
    param(
        [bool[]]$Results
    )

    Write-Evidence "Writing binder manifest..."

    # Get git info
    Push-Location $ROOT
    try {
        $gitCommit = git rev-parse HEAD 2>$null
        $gitBranch = git rev-parse --abbrev-ref HEAD 2>$null
    } catch {
        $gitCommit = "unknown"
        $gitBranch = "unknown"
    }
    Pop-Location

    # Collect artifact hashes
    $artifacts = @()
    $artifactFiles = Get-ChildItem -Path $BINDER_DIR -File
    foreach ($file in $artifactFiles) {
        if ($file.Name -ne "binder-manifest.json") {
            $artifacts += @{
                name = $file.Name
                size_bytes = $file.Length
                sha256 = Compute-SHA256 -Path $file.FullName
            }
        }
    }

    # Determine overall status
    $passCount = ($Results | Where-Object { $_ -eq $true }).Count
    $totalCount = $Results.Count
    $overallStatus = if ($passCount -eq $totalCount) { "PASS" } else { "WARN" }

    $manifest = @{
        binder_id = "binder-$TIMESTAMP"
        timestamp = (Get-Date -Format "o")
        git_commit = $gitCommit
        git_branch = $gitBranch
        artifact_count = $artifacts.Count
        artifacts = $artifacts
        checks_passed = $passCount
        checks_total = $totalCount
        overall_status = $overallStatus
    }

    $manifest | ConvertTo-Json -Depth 10 | Out-File -FilePath (Join-Path $BINDER_DIR "binder-manifest.json") -Encoding ASCII
    Write-Evidence "Manifest written: overall_status=$overallStatus ($passCount/$totalCount checks passed)"

    return $overallStatus
}

# --- Main Execution ---

Write-Evidence "=== SONIA Audit Evidence Collection ==="
Write-Evidence "Timestamp: $TIMESTAMP"
Write-Evidence "Binder: $BINDER_DIR"

# Create binder directory
if (-not (Test-Path $AUDIT_DIR)) {
    New-Item -ItemType Directory -Path $AUDIT_DIR -Force | Out-Null
}
New-Item -ItemType Directory -Path $BINDER_DIR -Force | Out-Null
Write-Evidence "Binder directory created"

# Collect latest Python gate artifacts from reports/audit/
function Collect-PythonGates {
    Write-Evidence "Collecting Python gate artifacts..."
    $gatePatterns = @(
        "secret-scan-*.json",
        "migration-verify-*.json",
        "backup-restore-drill-*.json",
        "incident-gate-*.json",
        "traceability-gate-*.json",
        "consolidated-preaudit-*.json",
        "redaction-verification-*.json",
        "rate-limiter-gate-*.json"
    )
    $collected = 0
    foreach ($pattern in $gatePatterns) {
        $latest = Get-ChildItem -Path $AUDIT_DIR -Filter $pattern -File -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($latest) {
            Copy-Item -Path $latest.FullName -Destination (Join-Path $BINDER_DIR $latest.Name)
            Write-Evidence "  Collected: $($latest.Name)"
            $collected++
        }
    }
    Write-Evidence "Collected $collected gate artifacts"
    return ($collected -ge 3)
}

# Collect all artifacts
$results = @(
    (Collect-GateReport -TargetRelease $Release),
    (Collect-SecurityScan),
    (Collect-BackupDrill),
    (Collect-RestoreVerification),
    (Collect-RedactionVerification),
    (Collect-ConfigFingerprint),
    (Collect-DocStamps),
    (Collect-PythonGates)
)

# Write manifest
$status = Write-BinderManifest -Results $results

Write-Evidence "=== Collection Complete ==="
Write-Evidence "Binder location: $BINDER_DIR"
Write-Evidence "Overall status: $status"

if ($status -eq "WARN") {
    Write-EvidenceWarn "Some artifacts missing or checks failed. Review binder-manifest.json for details."
}

exit 0
