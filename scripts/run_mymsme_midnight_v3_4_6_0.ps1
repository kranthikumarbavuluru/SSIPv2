param(
    [switch]$DryRun,
    [switch]$AllowUnpublishedRobots,
    [int]$MaxPages = 50,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$LogRoot = Join-Path $ProjectRoot "data\departments\msme\v3_4_6_0\mymsme\logs"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogPath = Join-Path $LogRoot ("midnight_" + $Stamp + ".log")
$Arguments = @("scripts\run_mymsme_agent_v3_4_6_0.py", "--mode", "full", "--max-pages", $MaxPages, "--json-report")
if ($DryRun) { $Arguments += "--dry-run" }
if ($AllowUnpublishedRobots) { $Arguments += "--allow-unpublished-robots" }
Push-Location $ProjectRoot
try {
    & $Python @Arguments 2>&1 | Tee-Object -FilePath $LogPath
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 0 }
    exit $exitCode
}
finally { Pop-Location }
