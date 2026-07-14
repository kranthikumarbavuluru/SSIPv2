Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$TaskName = "SSIP MeitY Purified Intelligence v3.4.3.8.0.1"
$AgentPath = Join-Path `
    $ProjectRoot `
    "agents\meity_candidate_purification_agent_v3_4_3_8_0_1.py"

if (-not (Test-Path $AgentPath)) {
    throw "Purification agent not found: $AgentPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument ('"' + $AgentPath + '"') `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "12:00 AM"

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
        "Refreshes official MeitY discovery and produces purified "
        "preview inventories. No database write or publication."
    ) `
    -Force

Write-Host "Nightly purified MeitY task registered."
Write-Host "Schedule: Daily at 12:00 AM"
Write-Host "Automatic database write: No"
Write-Host "Automatic publication: No"
