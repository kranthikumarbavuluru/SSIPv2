param(
    [string]$Python = "python",
    [string]$TaskName = "SSIP-MSME-Midnight-Governed-Agent",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$Wrapper = Join-Path $ProjectRoot "scripts\run_msme_midnight_v3_4_6_0.ps1"
if (-not (Test-Path $Wrapper)) { throw "Missing runner: $Wrapper" }
if ((Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -and -not $Force) {
    throw "Task already exists. Use -Force to update it explicitly."
}
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`" -Python `"$Python`"") -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 12:00am
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "SSIP governed MSME/AP MSME discovery and publication" -Force:$Force | Out-Null
Write-Output ("Installed " + $TaskName + " for daily midnight execution. The task is not run during installation.")
