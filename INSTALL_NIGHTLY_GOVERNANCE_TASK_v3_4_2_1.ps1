$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$taskName = "SSIP Nightly Catalogue Governance v3.4.2.1"
$runner = Join-Path $PSScriptRoot "RUN_NIGHTLY_GOVERNANCE_v3_4_2_1.ps1"
if (-not (Test-Path $runner)) { throw "Runner missing: $runner" }

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" `
    -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -Daily -At "12:00 AM"
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Sanitizes SSIP catalogue, separates calls, verifies startup relevance, maps sectors and publishes the public dashboard every midnight." `
    -Force | Out-Null

Write-Host "Installed: $taskName" -ForegroundColor Green
