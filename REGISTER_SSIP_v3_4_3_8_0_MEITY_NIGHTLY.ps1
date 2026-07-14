Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = "D:\WebSite\DASHBOARD\Code\SSIP_GitHub"
$TaskName = "SSIP MeitY Complete Intelligence v3.4.3.8.0"
$RunScript = Join-Path `
    $ProjectRoot `
    "RUN_SSIP_v3_4_3_8_0_MEITY_COMPLETE_PREVIEW.ps1"

if (-not (Test-Path $RunScript)) {
    throw "Run script not found: $RunScript"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument (
        '-NoProfile -ExecutionPolicy Bypass ' +
        '-File "' + $RunScript + '" ' +
        '-Mode live-preview'
    ) `
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
        "Runs the preview-only MeitY scheme, " +
        "programme, challenge and call intelligence agent. " +
        "No automatic database write or publication."
    ) `
    -Force

Write-Host "Nightly preview task registered: $TaskName"
Write-Host "Schedule: Daily at 12:00 AM"
Write-Host "Automatic publication: No"
