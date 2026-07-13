$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$taskName = "SSIP Nightly Agents v3.4.1.0"
$runner = Join-Path $PSScriptRoot "RUN_NIGHTLY_AGENTS_v3_4_1_0.ps1"
if (-not (Test-Path $runner)) { throw "Runner not found: $runner" }

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $PSScriptRoot

$trigger = New-ScheduledTaskTrigger -Daily -At "12:00 AM"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Runs SSIP scheme verification, sector mapping, evidence validation and dashboard publication every midnight." `
        -Force | Out-Null
}
catch {
    throw "Task creation failed. Open PowerShell as Administrator and rerun. Details: $($_.Exception.Message)"
}

Write-Host "Scheduled task installed: $taskName" -ForegroundColor Green
Write-Host "Schedule: Every day at 12:00 AM" -ForegroundColor Green
Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State
