param([string]$TaskName = "SSIP-MSME-Midnight-Governed-Agent")
$ErrorActionPreference = "Stop"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output ("Removed " + $TaskName)
} else { Write-Output ("Task not installed: " + $TaskName) }
