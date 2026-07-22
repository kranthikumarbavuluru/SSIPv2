param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskName = "SSIP Media Daily Pipeline",
    [string]$StartTime = "02:00"
)

$python = (Get-Command python -ErrorAction Stop).Source
$script = Join-Path $ProjectRoot "scripts\run_media_pipeline_v3_4_7_4.py"
$taskCommand = "`"$python`" `"$script`" --project-root `"$ProjectRoot`""

# Registration is explicit and reversible. This script does not run the task
# immediately and never deletes an existing task without user direction.
schtasks.exe /Create /TN $TaskName /SC DAILY /ST $StartTime /TR $taskCommand /F
Write-Output "Registered $TaskName for $StartTime. Remove with: schtasks.exe /Delete /TN `"$TaskName`" /F"
