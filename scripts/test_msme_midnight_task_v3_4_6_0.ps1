param([string]$TaskName = "SSIP-MSME-Midnight-Governed-Agent")
$ErrorActionPreference = "Stop"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { Write-Output ("Task not installed: " + $TaskName); exit 0 }
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object TaskName,LastRunTime,NextRunTime,LastTaskResult,NumberOfMissedRuns | Format-List
