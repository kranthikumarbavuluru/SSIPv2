Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$TaskName = "SSIP MeitY Decision Safety v3.4.3.8.0.3"
$AgentPath = Join-Path `
    $ProjectRoot `
    "agents\meity_temporal_parent_safety_agent_v3_4_3_8_0_3.py"

if (-not (Test-Path $AgentPath)) {
    throw "MeitY decision-safety agent not found: $AgentPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument ('"' + $AgentPath + '"') `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "12:30 AM"

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description (
        "Rebuilds MeitY decision bundles with temporal validation, " +
        "direct parent-link repair and safe Admin decision controls. " +
        "No database write or publication."
    ) `
    -Force

Write-Host "Nightly MeitY decision-safety task registered."
Write-Host "Schedule: Daily at 12:30 AM"
Write-Host "Automatic database write: No"
Write-Host "Automatic publication: No"
