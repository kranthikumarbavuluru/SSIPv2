$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$logDir = Join-Path $PSScriptRoot "logs\governance"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir ("nightly_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")
& powershell.exe -NoProfile -ExecutionPolicy Bypass `
    -File (Join-Path $PSScriptRoot "RUN_GOVERNANCE_AGENTS_v3_4_2_1.ps1") *>&1 |
    Tee-Object -FilePath $log
exit $LASTEXITCODE
