$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$logDir = Join-Path $PSScriptRoot "logs\agents"
New-Item -ItemType Directory -Force $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "nightly_$stamp.log"

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
        (Join-Path $PSScriptRoot "RUN_AGENTS_NOW_v3_4_1_0.ps1") *>&1 |
        Tee-Object -FilePath $logFile
    if ($LASTEXITCODE -ne 0) { throw "Nightly agent run failed with exit code $LASTEXITCODE." }
}
catch {
    $_ | Out-String | Add-Content -Path $logFile
    exit 1
}
