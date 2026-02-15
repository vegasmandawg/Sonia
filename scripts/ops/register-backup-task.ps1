<#
.SYNOPSIS
    Register or unregister Windows Task Scheduler task for memory DB backups
.DESCRIPTION
    Creates a scheduled task "SoniaMemoryBackup" that runs backup-memory-db.ps1
    daily at 2:00 AM. Can also unregister the task.
.PARAMETER Unregister
    If specified, removes the scheduled task instead of creating it
.PARAMETER RunLevel
    Task run level: 'Highest' or 'Limited'. Default is 'Highest' (runs as SYSTEM)
.EXAMPLE
    .\register-backup-task.ps1
    Registers the backup task to run daily at 2:00 AM
.EXAMPLE
    .\register-backup-task.ps1 -Unregister
    Removes the backup task
.EXAMPLE
    .\register-backup-task.ps1 -RunLevel Limited
    Registers the backup task to run as current user
#>

param(
    [switch]$Unregister,
    [ValidateSet('Highest', 'Limited')]
    [string]$RunLevel = 'Highest'
)

$ErrorActionPreference = "Stop"

$TaskName = "SoniaMemoryBackup"
$ScriptPath = "S:\scripts\ops\backup-memory-db.ps1"
$PowerShellExe = "powershell.exe"

# Verify script exists (unless unregistering)
if (-not $Unregister) {
    if (-not (Test-Path $ScriptPath)) {
        Write-Error "Backup script not found at $ScriptPath"
        exit 1
    }
}

if ($Unregister) {
    # Unregister task
    Write-Host "Unregistering scheduled task '$TaskName'..."

    try {
        $Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

        if ($Task) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "SUCCESS: Task '$TaskName' has been removed"
        } else {
            Write-Host "INFO: Task '$TaskName' not found (already removed or never created)"
        }

        exit 0

    } catch {
        Write-Error "Failed to unregister task: $($_.Exception.Message)"
        exit 1
    }

} else {
    # Register task
    Write-Host "Registering scheduled task '$TaskName'..."
    Write-Host "  Schedule: Daily at 2:00 AM"
    Write-Host "  Script: $ScriptPath"
    Write-Host "  Run Level: $RunLevel"

    try {
        # Check if task already exists
        $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($ExistingTask) {
            Write-Host "WARNING: Task '$TaskName' already exists. It will be replaced."
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        }

        # Create action: run PowerShell with backup script
        $Action = New-ScheduledTaskAction `
            -Execute $PowerShellExe `
            -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

        # Create trigger: daily at 2:00 AM
        $Trigger = New-ScheduledTaskTrigger -Daily -At "2:00AM"

        # Create principal (user context)
        if ($RunLevel -eq 'Highest') {
            # Run as SYSTEM with highest privileges
            $Principal = New-ScheduledTaskPrincipal `
                -UserId "SYSTEM" `
                -LogonType ServiceAccount `
                -RunLevel Highest
            Write-Host "  User: SYSTEM (service account)"
        } else {
            # Run as current user
            $Principal = New-ScheduledTaskPrincipal `
                -UserId $env:USERNAME `
                -LogonType Interactive `
                -RunLevel Limited
            Write-Host "  User: $env:USERNAME (current user)"
        }

        # Task settings
        $Settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -RunOnlyIfNetworkAvailable:$false `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1)

        # Register the task
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $Action `
            -Trigger $Trigger `
            -Principal $Principal `
            -Settings $Settings `
            -Description "Daily encrypted backup of SONIA memory-engine database" `
            | Out-Null

        Write-Host "SUCCESS: Task '$TaskName' has been registered"
        Write-Host ""
        Write-Host "To verify the task:"
        Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Format-List"
        Write-Host ""
        Write-Host "To run the task immediately (for testing):"
        Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
        Write-Host ""
        Write-Host "To unregister the task:"
        Write-Host "  .\register-backup-task.ps1 -Unregister"

        exit 0

    } catch {
        Write-Error "Failed to register task: $($_.Exception.Message)"
        exit 1
    }
}
