<#
.SYNOPSIS
    Create encrypted backup of memory-engine database
.DESCRIPTION
    Invokes the memory-engine db_backup module to create an encrypted backup
    and enforce retention policy. Logs results to S:\logs\backup\.
.PARAMETER DryRun
    If specified, only verifies the latest backup without creating a new one
.EXAMPLE
    .\backup-memory-db.ps1
    Creates a new backup and enforces retention
.EXAMPLE
    .\backup-memory-db.ps1 -DryRun
    Verifies the latest backup without creating a new one
#>

param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Paths
$PythonExe = "S:\envs\sonia-core\python.exe"
$LogDir = "S:\logs\backup"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogFile = Join-Path $LogDir "backup-$Timestamp.log"

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $Entry = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $Entry
    Add-Content -Path $LogFile -Value $Entry
}

Write-Log "====== Memory DB Backup Script ======"
Write-Log "Mode: $(if ($DryRun) { 'DRY RUN (verify only)' } else { 'LIVE (create backup)' })"

# Verify Python executable exists
if (-not (Test-Path $PythonExe)) {
    Write-Log "ERROR: Python executable not found at $PythonExe"
    exit 1
}

# Python script to run
$PythonScript = @"
import sys
sys.path.insert(0, r'S:\services\memory-engine')

try:
    from db_backup import create_backup, enforce_retention, verify_backup

    if $($DryRun.ToString().ToLower()):
        # Dry run: verify latest backup
        print('DRY RUN: Verifying latest backup...')
        result = verify_backup()
        if result:
            print(f'SUCCESS: Latest backup verified at {result}')
            sys.exit(0)
        else:
            print('ERROR: No valid backup found or verification failed')
            sys.exit(1)
    else:
        # Live run: create backup and enforce retention
        print('Creating encrypted backup...')
        backup_path = create_backup()
        print(f'Backup created: {backup_path}')

        print('Enforcing retention policy...')
        removed = enforce_retention()
        print(f'Retention enforced: {len(removed)} old backups removed')

        sys.exit(0)

except Exception as e:
    print(f'ERROR: {type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
"@

try {
    Write-Log "Executing backup operation..."

    # Run Python script and capture output
    $Output = & $PythonExe -c $PythonScript 2>&1
    $ExitCode = $LASTEXITCODE

    # Log all output
    foreach ($Line in $Output) {
        Write-Log $Line
    }

    if ($ExitCode -eq 0) {
        Write-Log "SUCCESS: Backup operation completed"
        Write-Log "Log file: $LogFile"
        exit 0
    } else {
        Write-Log "FAILURE: Backup operation failed with exit code $ExitCode"
        Write-Log "Log file: $LogFile"
        exit 1
    }

} catch {
    Write-Log "EXCEPTION: $($_.Exception.Message)"
    Write-Log "Stack trace: $($_.ScriptStackTrace)"
    Write-Log "Log file: $LogFile"
    exit 1
}
