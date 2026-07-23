param(
    [switch]$DryRun,
    [switch]$ChangedOnly,
    [switch]$RetryFailures,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$LogRoot = Join-Path $ProjectRoot "data\departments\msme\v3_4_6_0\logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogRoot ("midnight_" + $Stamp + ".log")
$Arguments = @("scripts\run_msme_agent_v3_4_6_0.py", "--mode", "full", "--json-report")
if ($DryRun) { $Arguments += "--dry-run" }
if ($ChangedOnly) { $Arguments += "--changed-only" }
if ($RetryFailures) { $Arguments += "--retry-failures" }
Push-Location $ProjectRoot
try {
    & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 0 }
    exit $exitCode
}
finally { Pop-Location }
