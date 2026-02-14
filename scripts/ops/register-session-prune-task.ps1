<#
.SYNOPSIS
    Registers the SoniaSessionPrune scheduled task (daily at 3AM).
#>
$ErrorActionPreference = "Stop"
$taskName = "SoniaSessionPrune"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task '$taskName' already registered"
    exit 0
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File S:\scripts\ops\prune-empty-sessions.ps1"

$trigger = New-ScheduledTaskTrigger -Daily -At "3:00AM"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Prune empty SONIA session files daily at 3AM" `
    -Force

Write-Host "Registered scheduled task: $taskName"
