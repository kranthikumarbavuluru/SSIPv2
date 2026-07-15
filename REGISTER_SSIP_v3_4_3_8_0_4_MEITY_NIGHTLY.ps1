Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$TaskName = "SSIP MeitY Link Integrity v3.4.3.8.0.4"
$AgentPath = Join-Path `
    $ProjectRoot `
    "agents\meity_url_integrity_agent_v3_4_3_8_0_4.py"

if (-not (Test-Path $AgentPath)) {
    throw "MeitY URL-integrity agent not found: $AgentPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument ('"' + $AgentPath + '"') `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "12:40 AM"

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
        "Validates MeitY final URLs, page roles, child provenance and " +
        "application-route integrity. Withholds unsafe links. No database " +
        "write or publication."
    ) `
    -Force

Write-Host "Nightly MeitY URL-integrity task registered."
Write-Host "Schedule: Daily at 12:40 AM"
Write-Host "Automatic database write: No"
Write-Host "Automatic publication: No"
