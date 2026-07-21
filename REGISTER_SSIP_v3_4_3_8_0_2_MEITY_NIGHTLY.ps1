Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$TaskName = "SSIP MeitY Family Review Compression v3.4.3.8.0.2"
$AgentPath = Join-Path `
    $ProjectRoot `
    "agents\meity_review_compression_agent_v3_4_3_8_0_2.py"

if (-not (Test-Path $AgentPath)) {
    throw "Review-compression agent not found: $AgentPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "python.exe" `
    -Argument ('"' + $AgentPath + '"') `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "12:20 AM"

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
        "Compresses purified MeitY evidence into automatic audit groups " +
        "and no more than 20 Admin decision bundles. No database write " +
        "or publication."
    ) `
    -Force

Write-Host "Nightly MeitY review-compression task registered."
Write-Host "Schedule: Daily at 12:20 AM"
Write-Host "Automatic database write: No"
Write-Host "Automatic publication: No"
