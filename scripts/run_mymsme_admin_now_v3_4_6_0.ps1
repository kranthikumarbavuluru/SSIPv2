param(
    [ValidateSet("discover", "candidate", "publish", "full", "status", "rollback")]
    [string]$Mode = "candidate",
    [switch]$Publish,
    [switch]$AllowUnpublishedRobots,
    [string]$RunId,
    [int]$MaxPages = 50,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$EffectiveMode = if ($Publish) { "publish" } else { $Mode }
$Arguments = @("scripts\run_mymsme_agent_v3_4_6_0.py", "--mode", $EffectiveMode, "--max-pages", $MaxPages, "--json-report")
if ($AllowUnpublishedRobots) { $Arguments += "--allow-unpublished-robots" }
if ($RunId) { $Arguments += "--run-id"; $Arguments += $RunId }
Push-Location $ProjectRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
}
finally { Pop-Location }
